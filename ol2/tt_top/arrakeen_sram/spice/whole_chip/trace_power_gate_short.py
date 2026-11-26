#!/usr/bin/env python3
"""Check one baseline power-gate control-to-VPWR GDS geometry witness."""
import argparse
import hashlib
from pathlib import Path
import sys

import klayout.db as db

from trace_q22_short import EXPECTED_GDS_SHA256, find_instance, find_label


def shared_root_components(root, control, power):
    """Return root polygons overlapping both distinct macro conductors."""
    if not (control & power).is_empty():
        raise ValueError("macro conductors must be distinct before root wiring")
    return [db.Region(p) for p in root.merged().each()
            if not (db.Region(p) & control).is_empty()
            and not (db.Region(p) & power).is_empty()]


def inspect(gds):
    digest = hashlib.sha256(gds.read_bytes()).hexdigest()
    if digest != EXPECTED_GDS_SHA256:
        raise ValueError(f"unexpected GDS SHA-256: {digest}")
    layout = db.Layout()
    layout.read(str(gds))
    top = layout.top_cell()
    if top is None or top.name != "tt_gf_wrapper" or layout.dbu != 0.001:
        raise ValueError("unexpected top cell or database unit")
    cell, transform = find_instance(top, "tt_pg_3v3_hp_1", "m90 2005360,125440")
    layer = layout.find_layer(46, 0)
    if layer is None:
        raise ValueError("Metal4 layer missing")
    metal = db.Region(cell.begin_shapes_rec(layer)).merged()
    control_label = find_label(layout, cell, 46, 10, "ctrl")
    power_label = find_label(layout, cell, 46, 10, "VPWR")

    def conductor(point):
        probe = db.Region(db.Box(point.x - 5, point.y - 5,
                                 point.x + 5, point.y + 5))
        result = metal.interacting(probe)
        if result.count() != 1:
            raise ValueError("label does not select exactly one macro conductor")
        return result.transformed(transform)

    control, power = conductor(control_label), conductor(power_label)
    root = db.Region(top.shapes(layer))
    hits = shared_root_components(root, control, power)
    if len(hits) != 1:
        raise ValueError(f"expected one shared root component, found {len(hits)}")
    return hits[0], control, power


def show(box):
    return tuple(round(x * 0.001, 5) for x in
                 (box.left, box.bottom, box.right, box.top))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gds", type=Path)
    args = parser.parse_args()
    try:
        root, control, power = inspect(args.gds)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"INCONCLUSIVE: {exc}", file=sys.stderr)
        return 2
    print("FAIL: root Metal4 component overlaps distinct power-gate ctrl and VPWR:")
    print(f"  ctrl overlap bbox {show((root & control).bbox())} um; "
          f"area {(root & control).area() * 1e-6:.6f} um²")
    print(f"  VPWR overlap bbox {show((root & power).bbox())} um; "
          f"area {(root & power).area() * 1e-6:.6f} um²")
    print("This targeted baseline witness is not full-chip DRC/LVS.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
