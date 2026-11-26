#!/usr/bin/env python3
"""Flatten every GDS child cell on import, but retain the top cell.

Requires gdstk. Generates commands only; does not read/write layout in Magic.
Use an empty work directory, matching PDK .magicrc, and a memory limit.
"""
import argparse
from pathlib import Path
import re

import gdstk


def generate(gds, magic_path, top, output):
    lib = gdstk.read_gds(str(gds))
    tops = [cell.name for cell in lib.top_level()]
    if tops != [top]:
        raise ValueError(f"expected only GDS top {top!r}, got {tops}")
    names = [cell.name for cell in lib.cells if cell.name != top]
    if len(names) != len(set(names)):
        raise ValueError("duplicate child-cell names")
    if any(not re.fullmatch(r"[A-Za-z0-9_.$-]+", name) for name in names):
        raise ValueError("a child-cell name contains Tcl or glob metacharacters")
    if any(c in magic_path for c in "{}\r\n"):
        raise ValueError("GDS path cannot contain braces or newlines")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", output):
        raise ValueError("SPICE output must be a simple filename")
    # Exact cell names are glob patterns without metacharacters, so each
    # matches only that child. The root name is intentionally omitted.
    commands = [f"gds flatglob {{{name}}}" for name in names]
    commands += [
        f"gds read {{{magic_path}}}",
        f"load {{{top}}}",
        "select top cell",
        "extract all",
        "ext2spice lvs",
        f"ext2spice -o {{{output}}}",
        "quit -noprompt",
    ]
    return "\n".join(commands) + "\n", len(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gds", required=True, type=Path,
                        help="GDS path readable by Python")
    parser.add_argument("--magic-gds-path", required=True,
                        help="same file path as seen by Magic")
    parser.add_argument("--top", default="tt_gf_wrapper")
    parser.add_argument("--spice-output", default="tt_gf_wrapper_from_gds.spice")
    parser.add_argument("--tcl-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        text, count = generate(args.gds, args.magic_gds_path, args.top, args.spice_output)
        with args.tcl_output.open("x", encoding="utf-8", newline="\n") as dest:
            dest.write(text)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Prepared {count} exact child-cell flatten patterns; "
          f"top {args.top} is not flattened.")


if __name__ == "__main__":
    main()
