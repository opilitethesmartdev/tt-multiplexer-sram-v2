#!/usr/bin/env python3
"""Make a syntax-only ngspice copy of a Magic extraction.

Magic emits the node token $SUB, which ngspice interprets as the start of a
comment. Replace that exact token with an unused identifier throughout the
file. Do not join, split, ground or otherwise alter any nodes.
"""
import argparse
import hashlib
from pathlib import Path
import re


SUBSTRATE = re.compile(rb"(?<!\S)\$SUB(?!\S)", re.IGNORECASE)
NEW_NAME = b"__magic_substrate"


def normalize(data):
    if NEW_NAME.lower() in data.lower():
        raise ValueError("replacement node name already exists")
    matches = list(SUBSTRATE.finditer(data))
    if not matches:
        raise ValueError("no standalone $SUB node tokens found")
    if data.count(b"$") != len(matches):
        raise ValueError("other dollar signs exist; refusing an incomplete rename")
    output = SUBSTRATE.sub(NEW_NAME, data)
    # Byte-for-byte reverse check ensures no unrelated change or net merge.
    if output.replace(NEW_NAME, b"$SUB") != data:
        raise ValueError("normalization was not byte-for-byte reversible")
    return output, len(matches)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        raw = args.source.read_bytes()
        result, count = normalize(raw)
        with args.output.open("xb") as f:
            f.write(result)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Renamed {count} node tokens, without modifying the original.")
    print(f"original SHA256:   {hashlib.sha256(raw).hexdigest()}")
    print(f"simulation SHA256: {hashlib.sha256(result).hexdigest()}")


if __name__ == "__main__":
    main()
