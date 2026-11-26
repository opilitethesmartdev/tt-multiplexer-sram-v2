#!/usr/bin/env python3
"""Check GDS power-gate control labels for direct root Metal4 supply shorts.

This deliberately narrow geometry regression does not perform LVS, find
multi-layer paths, or certify the complete layout. It does not alter GDS.
"""
import argparse
import hashlib
from pathlib import Path
import sys

import klayout.db as db
from trace_q22_short import find_label


def root_bridges(root, control, supply):
    """Return merged root components with positive overlap on both regions."""
    return [db.Region(poly) for poly in root.interacting(control).each()
            if not (db.Region(poly) & control).is_empty()
            and not (db.Region(poly) & supply).is_empty()]


def inspect(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    layout = db.Layout()
    layout.read(str(path))
    top = layout.top_cell()
    if top is None or top.name != "tt_gf_wrapper":
        raise ValueError("expected a single tt_gf_wrapper top")
    layer = layout.find_layer(46, 0)
    if layer is None or layout.dbu != 0.001:
        raise ValueError("unexpected GF180 Metal4 layer or DBU")
    root = db.Region(top.shapes(layer)).merged()
    instances = [(inst.cell, inst.trans.dup()) for inst in top.each_inst()
                 if inst.cell.name.startswith("tt_pg_3v3_hp_")]
    if not instances:
        raise ValueError("no expected power-gate instances found")
    violations = []
    for cell, transform in instances:
        macro = db.Region(cell.begin_shapes_rec(layer)).merged()

        def label_conductor(name):
            p = find_label(layout, cell, 46, 10, name)
            selected = macro.interacting(db.Region(db.Box(p.x - 5, p.y - 5,
                                                         p.x + 5, p.y + 5)))
            if selected.count() != 1:
                raise ValueError(f"{cell.name}/{name} does not select one conductor")
            return selected.transformed(transform)

        control = label_conductor("ctrl")
        for pin in ("VGND", "VPWR", "GPWR"):
            supply = label_conductor(pin)
            if not (control & supply).is_empty():
                raise ValueError(f"{cell.name} control/supply already merged inside macro")
            if root_bridges(root, control, supply):
                violations.append((cell.name, str(transform), pin))
    return digest, len(instances), violations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gds", type=Path)
    args = parser.parse_args()
    try:
        digest, count, violations = inspect(args.gds)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"INCONCLUSIVE: {exc}", file=sys.stderr)
        return 2
    print(f"GDS SHA-256 {digest}; checked {count} power gates")
    for master, transform, pin in violations:
        print(f"FAIL: {master} {transform} ctrl shares root Metal4 with {pin}")
    if violations:
        return 1
    print("No direct root-Metal4 gate-control-to-supply bridge found; not sign-off.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
