#!/usr/bin/env python3
"""Vary only the last write data/enable hold time in a GDS SRAM probe."""
import argparse
from pathlib import Path
import re


def variant(text, hold_ns):
    # Vclk's final write rising transition is 1100n..1101n. Move the
    # data/WE falling transition, leaving the address and every other input
    # unchanged. This varies *both* data and WE; it does not characterize
    # their individual hold times or setup time.
    if not 1 <= hold_ns <= 100:
        raise ValueError("hold must be an integer from 1 to 100 ns")
    if not text.startswith("* Exploratory GDS pilot:"):
        raise ValueError("expected a prepared GDS SRAM deck")
    lines = text.splitlines()
    changed = 0
    for i, line in enumerate(lines):
        if re.match(r"^V(?:we[0-3]|d(?:[0-9]|[12][0-9]|3[01]))\s", line, re.I):
            if "1249n" in line and "1250n" in line:
                lines[i] = line.replace("1249n", f"{1101 + hold_ns}n").replace(
                    "1250n", f"{1102 + hold_ns}n")
                changed += 1
    if changed != 20:
        raise ValueError(f"expected to change 20 active sources, got {changed}")
    result = "\n".join(lines) + "\n"
    if result.count("bank_wave.dat") != 1:
        raise ValueError("expected a single waveform output")
    return (f"* Exploratory simultaneous data/WE hold {hold_ns} ns after clock high.\n" +
            result.replace("bank_wave.dat", f"bank_hold_{hold_ns}ns.dat"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--hold-ns", type=int, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite output")
    try:
        args.output.write_text(variant(args.input.read_text(encoding="utf-8"),
                                       args.hold_ns), encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
