#!/usr/bin/env python3
"""Adapt the unchanged SRAM write-address stimulus to the flat GDS pilot.

The raw GDS netlist is not modified. This exploratory bench explicitly ties
vdd and vdd_uq0 externally, an unverified supply assumption, and uses the
same behavioral-model expectations as bank_write_address. It is not LVS.
"""
import argparse
import hashlib
from pathlib import Path
import re


EXPECTED = "2fad185c295c5b6907008f8fc5f429e29096e6d4fbf281dd7214ad4d2b53c5cc"


def quote(path):
    text = str(path.resolve(strict=True))
    if any(c in text for c in '"\n\r'):
        raise ValueError("unsupported character in SPICE include path")
    return '"' + text + '"'


def port_map(port):
    if port.lower() == "vss":
        return "0"
    if port.lower() in ("vdd", "vdd_uq0"):
        return "vdd"
    if port.lower() == "clk":
        return "clk"
    match = re.fullmatch(r"(a|q|d|we)\[(\d+)\]", port, re.I)
    if not match:
        raise ValueError(f"unrecognized macro port: {port}")
    return match.group(1).lower() + match.group(2)


def prepare(raw, models, template):
    content = raw.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != EXPECTED:
        raise ValueError(f"unrecognized raw SRAM extraction hash {digest}")
    lines = content.decode("utf-8").splitlines()
    index = next((i for i, line in enumerate(lines)
                  if line.lower().startswith(".subckt sp6tsram256x32 ")), None)
    if index is None:
        raise ValueError("SRAM top subcircuit missing")
    ports = lines[index].split()[2:]
    index += 1
    while index < len(lines) and lines[index].startswith("+"):
        ports.extend(lines[index][1:].split())
        index += 1
    expected = ({"vss", "vdd", "vdd_uq0", "clk"} |
                {f"a[{n}]" for n in range(8)} |
                {f"q[{n}]" for n in range(32)} |
                {f"d[{n}]" for n in range(32)} |
                {f"we[{n}]" for n in range(4)})
    if len(ports) != len(expected) or {p.lower() for p in ports} != expected:
        raise ValueError("unexpected extracted SRAM port list")
    deck = template.read_text(encoding="utf-8")
    if deck.count('.include "models.spice"') != 1 or \
            deck.count('.include "SP6TSRAM256x32.spice"') != 1:
        raise ValueError("unexpected stimulus template")
    deck = deck.replace('.include "models.spice"',
                        f'.include {quote(models / "design.ngspice")}\n'
                        f'.lib {quote(models / "sm141064.ngspice")} typical')
    deck = deck.replace('.include "SP6TSRAM256x32.spice"', f'.include {quote(raw)}')
    line = "Xmem " + " ".join(port_map(port) for port in ports) + " SP6TSRAM256x32"
    deck, count = re.subn(r"(?m)^Xmem .*SP6TSRAM256x32[ \t]*$", line, deck)
    if count != 1:
        raise ValueError("expected one template macro instance")
    return ("* Exploratory GDS pilot: vdd and vdd_uq0 externally tied to 3.3 V;\n"
            "* supplies/port mapping are assumptions, no LVS or sign-off.\n" + deck)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite output")
    try:
        deck = prepare(args.raw, args.models, args.template)
        args.output.write_text(deck, encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print("Prepared exploratory GDS SRAM probe; raw netlist unchanged.")


if __name__ == "__main__":
    main()
