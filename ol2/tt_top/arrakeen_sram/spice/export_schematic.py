#!/usr/bin/env python3
"""Export the actual compiler schematic; this is not extracted layout."""
import argparse
from pathlib import Path

from c4m.pdk import gf180mcu


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    library = gf180mcu.Library(name="SP6TSRAM256x32")
    factory = gf180mcu.SPSRAMFactory(lib=library, name_prefix="SP6T")
    cell = factory.block(words=256, word_size=32, we_size=4,
                         cell_name="SRAM256x32")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    text = gf180mcu.netlistfab.export_circuits(cell.circuit, add_subcircuits=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as output:
        output.write("* Arrakeen compiler schematic, not GDS extraction\n"
                     + text.rstrip() + "\n")
    print(f"Wrote {args.output}; {len(cell.circuit.ports)} macro ports")


if __name__ == "__main__":
    main()
