#!/usr/bin/env python3
"""Generate deterministic ngspice decks for the Arrakeen 256x32 bank."""
import argparse
import json
from pathlib import Path
import re


PORTS = (["clk"] + [f"a[{i}]" for i in range(8)] + ["vss", "vdd"]
         + [f"q[{i}]" for i in range(32)]
         + [f"d[{i}]" for i in range(32)]
         + [f"we[{i}]" for i in range(4)])


def macro_ports(text):
    match = re.search(r"(?im)^\.subckt\s+SP6TSRAM256x32\s+([^\n]*)", text)
    if not match:
        raise ValueError("SP6TSRAM256x32 .subckt is missing")
    tail = text[match.end():].splitlines()
    ports = match.group(1).split()
    for line in tail:
        if not line.lstrip().startswith("+"):
            break
        ports.extend(line.lstrip()[1:].split())
    if [p.lower() for p in ports] != PORTS:
        raise ValueError("macro port order differs from expected compiler schematic")
    # Refuse the black-box-only LVS view, which cannot simulate memory.
    if not re.search(r"(?im)^\.subckt\s+SP6TCell\s+", text):
        raise ValueError("SP6TCell is missing; macro may be an LVS black box")


def voltage_source(name, points):
    return f"V{name} {name} 0 PWL(" + " ".join(
        f"{t:g}n {'{VDD}' if level else '0'}" for t, level in points) + ")"


def common(title):
    return [f"* {title}", "* Compiler schematic; not post-layout extraction.",
            '.include "models.spice"', '.include "SP6TSRAM256x32.spice"',
            ".param VDD=3.3", ".temp 25", ".options reltol=1e-3 klu",
            "Vdd vdd 0 DC {VDD}"]


def cell_deck():
    lines = common("Actual Arrakeen 6T bitcell: write, hold and read")
    lines += [
        "Xbit 0 0 vdd vdd wl bl blb SP6TCell",
        "Cbl bl 0 10f", "Cblb blb 0 10f",
        ".model sw sw(ron=10 roff=1e12 vt=1.65 vh=0)",
        "Sp0 bl  vdd pre 0 sw", "Sp1 blb vdd pre 0 sw",
        "Sw00 bl  0   w0 0 sw", "Sw01 blb vdd w0 0 sw",
        "Sw10 bl  vdd w1 0 sw", "Sw11 blb 0   w1 0 sw",
        voltage_source("wl", [(0, 0), (10, 0), (11, 1), (30, 1), (31, 0),
                               (60, 0), (61, 1), (80, 1), (81, 0),
                               (100, 0), (101, 1), (120, 1), (121, 0),
                               (150, 0), (151, 1), (170, 1), (171, 0)]),
        voltage_source("w0", [(0, 0), (2, 0), (3, 1), (35, 1), (36, 0)]),
        voltage_source("w1", [(0, 0), (92, 0), (93, 1), (125, 1), (126, 0)]),
        voltage_source("pre", [(0, 0), (40, 0), (41, 1), (57, 1), (58, 0),
                                (130, 0), (131, 1), (147, 1), (148, 0)]),
        ".save v(xbit.bit) v(xbit.bit_n) v(bl) v(blb) v(wl) i(Vdd)",
        ".tran 0.1n 190n 0 0.2n",
        ".meas tran cell_zero find v(xbit.bit) at=45n",
        ".meas tran cell_one find v(xbit.bit) at=135n",
        ".meas tran cell_after_read0 find v(xbit.bit) at=85n",
        ".meas tran cell_after_read1 find v(xbit.bit) at=175n",
        ".meas tran cell_read0_bl find v(bl) at=78n",
        ".meas tran cell_read0_blb find v(blb) at=78n",
        ".meas tran cell_read1_bl find v(bl) at=168n",
        ".meas tran cell_read1_blb find v(blb) at=168n",
        ".control", "run", "wrdata bitcell_wave.dat v(xbit.bit) v(xbit.bit_n) v(bl) v(blb) v(wl) i(Vdd)",
        "quit", ".endc", ".end",
    ]
    return "\n".join(lines) + "\n"


def bank_deck(title, events, samples, stop):
    # Each event is (rising-edge ns, address, lane mask, data).
    lines = common(title)
    mapping = (["clk"] + [f"a{i}" for i in range(8)] + ["0", "vdd"]
               + [f"q{i}" for i in range(32)]
               + [f"d{i}" for i in range(32)] + [f"we{i}" for i in range(4)])
    lines.append("Xmem " + " ".join(mapping) + " SP6TSRAM256x32")
    for bit in range(32):
        lines.append(f"Cq{bit} q{bit} 0 10f")
    # Inputs settle at least 50 ns before each clock edge.
    for prefix, width, field in (("a", 8, 1), ("we", 4, 2), ("d", 32, 3)):
        for bit in range(width):
            initial = (events[0][field] >> bit) & 1
            points = [(0, initial)]
            for edge, address, mask, data in events[1:]:
                value = ((address, mask, data)[field - 1] >> bit) & 1
                old = points[-1][1]
                if value != old:
                    points += [(edge - 51, old), (edge - 50, value)]
            lines.append(voltage_source(f"{prefix}{bit}", points))
    clock_points = [(0, 0)]
    for edge, _, _, _ in events:
        clock_points += [(edge, 0), (edge + 1, 1),
                         (edge + 90, 1), (edge + 91, 0)]
    lines.append(voltage_source("clk", clock_points))
    lines.append(".save " + " ".join(f"v(q{i})" for i in range(32))
                 + " v(clk) i(Vdd)")
    lines.append(f".tran 0.5n {stop}n 0 1n")
    for sample, time, _ in samples:
        for bit in range(32):
            lines.append(f".meas tran q{bit}_{sample} find v(q{bit}) at={time}n")
    lines += [".control", "run",
              "wrdata bank_wave.dat " + " ".join(f"v(q{i})" for i in range(32))
              + " v(clk) i(Vdd)", "quit", ".endc", ".end"]
    return "\n".join(lines) + "\n"


def dual_bank_deck(events, samples):
    """Two physical macros with externally sequenced bank enables.

    This is not a transistor-level model of tt_top's RTL bank selector.
    """
    lines = common("Two 256x32 banks: selected writes and cross-bank isolation")
    for bank in ("l", "h"):
        pins = (["clk"] + [f"a{i}" for i in range(8)] + ["0", "vdd"]
                + [f"q{bank}{i}" for i in range(32)]
                + [f"d{i}" for i in range(32)]
                + [f"we{bank}{i}" for i in range(4)])
        lines.append(f"X{bank} " + " ".join(pins) + " SP6TSRAM256x32")
        lines += [f"Cq{bank}{bit} q{bank}{bit} 0 10f" for bit in range(32)]
    # Event fields: edge, address, low mask, high mask, shared data.
    for prefix, width, field in (("a", 8, 1), ("wel", 4, 2),
                                 ("weh", 4, 3), ("d", 32, 4)):
        for bit in range(width):
            points = [(0, (events[0][field] >> bit) & 1)]
            for event in events[1:]:
                edge = event[0]
                value = (event[field] >> bit) & 1
                old = points[-1][1]
                if value != old:
                    points += [(edge - 51, old), (edge - 50, value)]
            lines.append(voltage_source(f"{prefix}{bit}", points))
    clock = [(0, 0)]
    for edge, *_ in events:
        clock += [(edge, 0), (edge + 1, 1), (edge + 90, 1), (edge + 91, 0)]
    lines.append(voltage_source("clk", clock))
    lines += [".save " + " ".join(f"v(q{bank}{i})"
                                  for bank in ("l", "h") for i in range(32))
              + " v(clk) i(Vdd)", ".tran 0.5n 1250n 0 1n"]
    for sample, time, _, _ in samples:
        for bank in ("l", "h"):
            for bit in range(32):
                lines.append(f".meas tran q{bank}{bit}_{sample} "
                             f"find v(q{bank}{bit}) at={time}n")
    lines += [".control", "run",
              "wrdata dual_wave.dat " + " ".join(f"v(q{bank}{i})"
                   for bank in ("l", "h") for i in range(32))
              + " v(clk) i(Vdd)", "quit", ".endc", ".end"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    schematic = args.output / "SP6TSRAM256x32.spice"
    if schematic.exists():
        macro_ports(schematic.read_text(encoding="utf-8"))
    a, b, c = 0xaa55aa55, 0x55aa55aa, 0x12345678
    patched = (a & 0xff00ff00) | (c & 0x00ff00ff)
    functional_events = [(100, 0, 0, 0), (300, 255, 15, a),
                         (500, 0, 15, b), (700, 255, 5, c),
                         (900, 0, 0, 0), (1100, 255, 0, 0),
                         (1300, 0, 0, 0)]
    functional_samples = [("s0", 980, patched), ("s1", 1180, b),
                          ("s2", 1380, patched)]
    retention_events = [(100, 17, 0, 0), (300, 18, 15, a),
                        (2100, 17, 0, 0), (2300, 17, 15, b),
                        (2500, 17, 0, 0), (4100, 17, 0, 0)]
    retention_samples = [("s0", 2180, a), ("s1", 2580, b),
                         ("s2", 4180, b)]
    # Hold each write address for two edges to remove write-address
    # ambiguity. For each subsequent address change, observe both the
    # first and second read edges against the compiler's Verilog model.
    address_events = [(100, 0, 0, 0), (300, 0, 15, a),
                      (500, 255, 0, 0), (700, 255, 15, b),
                      (900, 0, 0, 0), (1100, 0, 0, 0),
                      (1300, 255, 0, 0), (1500, 255, 0, 0)]
    address_samples = [("s0", 980, a), ("s1", 1180, a),
                       ("s2", 1380, b), ("s3", 1580, b)]
    # Initialize both words to zero with stable addresses, capture address 0,
    # then change to 255 at the write edge. The Verilog writes the previously
    # captured address 0; a circuit writing the current address writes 255.
    write_address_events = [(100, 0, 0, 0), (300, 0, 15, 0),
                            (500, 255, 0, 0), (700, 255, 15, 0),
                            (900, 0, 0, 0), (1100, 255, 15, a),
                            (1300, 0, 0, 0), (1500, 255, 0, 0)]
    write_address_samples = [("s0", 1380, a), ("s1", 1580, 0)]
    dual_events = [(100, 3, 0, 0, 0), (300, 3, 15, 0, a),
                   (500, 3, 0, 15, b), (700, 3, 0, 0, 0),
                   (900, 3, 5, 0, c), (1100, 3, 0, 0, 0)]
    dual_samples = [("s0", 780, a, b), ("s1", 1180, patched, b)]
    for name, content in (
        ("bitcell.spice", cell_deck()),
        ("bank_functional.spice", bank_deck(
            "Single 256x32 bank: addresses 0 and 255, full and byte writes",
            functional_events, functional_samples, 1450)),
        ("bank_retention.spice", bank_deck(
            "Single 256x32 bank: initialized data with stopped-clock holds",
            retention_events, retention_samples, 4250)),
        ("bank_address_pipeline.spice", bank_deck(
            "Single bank: address held for writes, first versus second read edge",
            address_events, address_samples, 1650)),
        ("bank_write_address.spice", bank_deck(
            "Single bank: distinguish previous versus current write address",
            write_address_events, write_address_samples, 1650)),
        ("dual_bank_isolation.spice", dual_bank_deck(dual_events, dual_samples)),
    ):
        (args.output / name).write_text(content, encoding="utf-8")
    manifest = {name: [{"sample": sample, "time_ns": time, "expected": f"{word:08x}"}
                       for sample, time, word in samples]
                for name, samples in (("bank_functional", functional_samples),
                                      ("bank_retention", retention_samples),
                                      ("bank_address_pipeline", address_samples),
                                      ("bank_write_address", write_address_samples))}
    manifest["dual_bank_isolation"] = [
        {"sample": sample, "time_ns": time, "low": f"{low:08x}", "high": f"{high:08x}"}
        for sample, time, low, high in dual_samples
    ]
    (args.output / "expected.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                               encoding="utf-8")
    print(f"Generated decks and expected.json in {args.output}")


if __name__ == "__main__":
    main()
