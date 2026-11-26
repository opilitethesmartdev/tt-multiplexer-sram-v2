#!/usr/bin/env python3
"""Create a local model include for an installed GF180 open_pdks model set."""
import argparse
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True,
                        help="directory containing design.ngspice and sm141064.ngspice")
    parser.add_argument("--corner", choices=("typical", "ff", "ss", "fs", "sf"),
                        default="typical")
    parser.add_argument("--output", type=Path, default=Path("models.spice"))
    args = parser.parse_args()
    model_dir = args.model_dir.resolve()
    design = model_dir / "design.ngspice"
    models = model_dir / "sm141064.ngspice"
    for path in (design, models):
        if not path.is_file():
            parser.error(f"missing PDK model file: {path}")
        if '"' in str(path) or "\n" in str(path):
            parser.error("model paths must not contain quotes or newlines")
    text = models.read_text(encoding="utf-8", errors="replace")
    if not re.search(rf"(?im)^\s*\.lib\s+{args.corner}\s*$", text):
        parser.error(f"model file lacks .lib {args.corner}")
    args.output.write_text(
        f'* GF180 model directory: {model_dir}\n'
        f'.include "{design.as_posix()}"\n'
        f'.lib "{models.as_posix()}" {args.corner}\n',
        encoding="utf-8")
    print(f"Wrote {args.output} for {args.corner}")


if __name__ == "__main__":
    main()
