#!/usr/bin/env python3
"""Prepare an exploratory whole-GDS factory-test SPICE deck.

The exact input file is never modified. Acknowledgement is required because
the extraction has unresolved feedback and a signal tied to a supply.
This does not test SRAM through a user tile or constitute silicon sign-off.
"""
import argparse
import hashlib
from pathlib import Path
import re

from audit_spice import audit
from normalize_magic_spice import normalize


EXPECTED_GDS_SPICE_SHA256 = "87b2ef7725362b3d7d5ffff650acb6c39ca0553a32a6879f46a8a20003865c72"
DEVICE_SUBCKTS = {"nfet_03v3", "pfet_03v3", "nfet_05v0", "pfet_05v0"}


def quote(path):
    value = str(path.resolve())
    if '"' in value or "\n" in value or "\r" in value:
        raise ValueError("SPICE include paths cannot contain quotes or newlines")
    return '"' + value + '"'


def map_port(port):
    match = re.fullmatch(r"pad_raw\[(\d+)\]", port, re.I)
    if match:
        return f"p{int(match.group(1))}"
    base = re.sub(r"_uq\d+$", "", port.lower())
    if base in {"vccd", "vccd1", "vccd2", "vdda", "vdda1", "vdda2", "vddio"}:
        return "vdd"
    if base in {"vssa", "vssa1", "vssa2", "vssd", "vssd1", "vssd2", "vssio"}:
        return "0"
    raise ValueError(f"unrecognized physical top port: {port}")


def deck(raw, design, model, ports):
    node_list = " ".join(map_port(port) for port in ports)
    lines = [
        "* Exploratory full-GDS factory test; not sign-off or SRAM access.",
        "* All power pad groups are tied to one 3.3 V source for this test.",
        "* External UIO drivers use 1 kohm series resistance; inspect currents.",
        f".include {quote(design)}",
        f".lib {quote(model)} typical",
        f".lib {quote(model)} diode_typical",
        f".include {quote(raw)}",
        ".param VDD=3.3",
        ".temp 25",
        ".options klu reltol=1e-3",
        "Vdd vdd 0 PWL(0 0 20n 0 120n {VDD})",
        "Xchip " + node_list + " tt_gf_wrapper",
        "Vctrl_ena p0 0 PWL(0 0 2400n 0 2401n {VDD})",
        "Vctrl_inc p1 0 PWL(0 0 1800n 0 1801n {VDD} 2000n {VDD} 2001n 0)",
        "Vctrl_reset p2 0 PWL(0 0 1000n 0 1001n {VDD})",
        "Vreset p54 0 PWL(0 0 3400n 0 3401n {VDD})",
        "Vclk p55 0 PULSE(0 {VDD} 200n 1n 1n 99n 200n)",
    ]
    for bit in range(8):
        lines.append(f"Vui{bit} p{46+bit} 0 0")
        a, b = (0xa5 >> bit) & 1, (0x5a >> bit) & 1
        va, vb = ("{VDD}" if a else "0"), ("{VDD}" if b else "0")
        lines += [
            f"Vuio{bit} src{bit} 0 PWL(0 0 4000n 0 4001n {va} "
            f"4500n {va} 4501n {vb})",
            f"Ruio{bit} src{bit} p{37+bit} 1k",
            f"Cout{bit} p{9+bit} 0 10f",
        ]
    save = [f"v(p{n})" for n in range(9, 17)] + [
        f"v(p{n})" for n in range(37, 45)
    ] + ["v(vdd)", "i(Vdd)", "v(p0)", "v(p1)", "v(p2)", "v(p54)", "v(p55)"]
    lines += [".save " + " ".join(save), ".tran 1n 5u 0 2n"]
    for phase, when in (("a", 4250), ("b", 4750)):
        for bit in range(8):
            lines.append(f".meas tran input{bit}_{phase} find v(p{37+bit}) at={when}n")
            lines.append(f".meas tran output{bit}_{phase} find v(p{9+bit}) at={when}n")
            lines.append(f".meas tran current{bit}_{phase} find i(Vuio{bit}) at={when}n")
    lines += [".control", "run", "wrdata factory_wave.dat " + " ".join(save),
              "quit", ".endc", ".end"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-spice", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--simulation-copy", type=Path,
                        help="optional syntax-only $SUB-renamed copy of raw SPICE")
    parser.add_argument("--ack-extraction-warnings", action="store_true")
    args = parser.parse_args()
    if not args.ack_extraction_warnings:
        parser.error("this extraction is unsafe to trust; pass "
                     "--ack-extraction-warnings for an exploratory run")
    try:
        raw = args.raw_spice.resolve(strict=True)
        original = raw.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        if digest != EXPECTED_GDS_SPICE_SHA256:
            raise ValueError(f"unrecognized raw GDS SPICE hash: {digest}")
        design = (args.model_dir / "design.ngspice").resolve(strict=True)
        model = (args.model_dir / "sm141064.ngspice").resolve(strict=True)
        result = audit([raw], "tt_gf_wrapper")
        if result["empty"] or set(result["missing"]) != DEVICE_SUBCKTS:
            raise ValueError("unexpected hierarchy; inspect with audit_spice.py")
        if result["bad_arity"] or result["disconnected_supply_groups"]:
            raise ValueError("unexpected top arity or supply-port problem")
        if len(result["top"].ports) != 96:
            raise ValueError("unexpected top-level port count")
        simulation = raw
        if args.simulation_copy:
            simulation = args.simulation_copy.resolve(strict=True)
            expected, count = normalize(original)
            if simulation.read_bytes() != expected:
                raise ValueError("simulation copy differs beyond the $SUB syntax rename")
            print(f"Verified syntax-only rename of {count} $SUB tokens.")
        text = deck(simulation, design, model, result["top"].ports)
        if args.output.exists():
            raise ValueError(f"refusing to overwrite {args.output}")
        args.output.write_text(text, encoding="utf-8", newline="\n")
        print("Prepared exploratory deck; no extracted connectivity was altered.")
        print("WARNING: raw GDS extraction reports q[22] on ground and 129538 "
              "label-overlap warnings; this run cannot establish silicon safety.")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
