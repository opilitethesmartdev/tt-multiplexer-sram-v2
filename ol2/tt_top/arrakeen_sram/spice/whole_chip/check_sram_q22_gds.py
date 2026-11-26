#!/usr/bin/env python3
"""Check the low SRAM q[22] against nearby standard-cell VSS in drawn GDS.

The localized test can miss paths that leave its window; a pass is not LVS.
"""
import argparse
import hashlib
from pathlib import Path
import sys

import klayout.db as db
from trace_q22_short import LAYERS, find_label, path_between


def inspect(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    layout = db.Layout()
    layout.read(str(path))
    top = layout.top_cell()
    if top is None or top.name != "tt_gf_wrapper" or layout.dbu != 0.001:
        raise ValueError("unexpected top or GDS database unit")
    srams = [(inst.cell, inst.trans.dup()) for inst in top.each_inst()
             if inst.cell.name == "SP6TSRAM256x32"]
    if len(srams) != 2:
        raise ValueError(f"expected two SRAMs, found {len(srams)}")
    # The low bank is the upper of the two fixed banks in this floorplan.
    cell, trans = max(srams, key=lambda item: item[1].disp.y)
    q = trans * find_label(layout, cell, 42, 10, "q[22]")
    window = db.Box(q.x - 20000, q.y - 20000, q.x + 20000, q.y + 20000)
    ground = db.Region()
    count = 0
    label_cache = {}
    for inst in top.each_inst():
        if not inst.cell.name.startswith("gf180mcu_fd_sc_"):
            continue
        if not inst.bbox().overlaps(window):
            continue
        if inst.cell.cell_index() not in label_cache:
            try:
                label_cache[inst.cell.cell_index()] = find_label(
                    layout, inst.cell, 34, 10, "VSS")
            except ValueError:
                label_cache[inst.cell.cell_index()] = None
        label = label_cache[inst.cell.cell_index()]
        if label is None:
            continue
        point = inst.trans * label
        if window.contains(point):
            ground += db.Region(db.Box(point.x - 5, point.y - 5,
                                       point.x + 5, point.y + 5))
            count += 1
    if not count:
        raise ValueError("no nearby labeled standard-cell VSS in the check window")
    regions = {}
    for name, number in LAYERS.items():
        index = layout.find_layer(number, 0)
        if index is None:
            raise ValueError(f"GDS layer {number}/0 missing")
        regions[name] = db.Region(top.begin_shapes_rec_touching(index, window)) & db.Region(window)
    probe = db.Region(db.Box(q.x - 5, q.y - 5, q.x + 5, q.y + 5))
    witness = path_between(regions, probe, ground)
    return digest, q, count, witness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gds", type=Path)
    args = parser.parse_args()
    try:
        digest, q, count, witness = inspect(args.gds)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"INCONCLUSIVE: {exc}", file=sys.stderr)
        return 2
    print(f"GDS SHA-256 {digest}; q[22] at {q}; {count} nearby VSS labels")
    if witness:
        print("FAIL: positive-overlap metal/via path from q[22] to a nearby cell VSS")
        for layer, box in witness:
            coords = tuple(round(v * 0.001, 5) for v in
                           (box.left, box.bottom, box.right, box.top))
            print(f"  {layer}: {coords} um")
        return 1
    print("No local path found; other paths and the rest of the chip are not checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
