#!/usr/bin/env python3
"""Find the baseline GDS's q[22] to VSS positive-area metal/via path.

Uses drawn GF180 GDS layers only; no Magic-extracted net names. A found path
is a geometry witness, not a complete foundry DRC/LVS. A missing path does not
prove the design clean, especially outside the small clipped window.
"""
import argparse
from collections import deque
import hashlib
from pathlib import Path
import sys

import klayout.db as db


EXPECTED_GDS_SHA256 = "2117d03c0758f77ef09e555877f68f730747b29d89e82bc2907dd2b111c0918f"
LAYERS = {"m1": 34, "v1": 35, "m2": 36, "v2": 38, "m3": 42,
          "v3": 40, "m4": 46, "v4": 41, "m5": 81}
ADJACENT = {"m1": ("v1",), "v1": ("m1", "m2"), "m2": ("v1", "v2"),
            "v2": ("m2", "m3"), "m3": ("v2", "v3"),
            "v3": ("m3", "m4"), "m4": ("v3", "v4"),
            "v4": ("m4", "m5"), "m5": ("v4",)}


def path_between(regions, q_probe, gnd_probe):
    """BFS across merged same-layer geometry and overlapping via cuts."""
    polygons = {name: [db.Region(p) for p in regions[name].merged().each()]
                for name in LAYERS}
    sources = [("m3", i) for i, p in enumerate(polygons["m3"])
               if not (p & q_probe).is_empty()]
    targets = {("m1", i) for i, p in enumerate(polygons["m1"])
               if not (p & gnd_probe).is_empty()}
    if not sources or not targets:
        raise ValueError("the GDS labels do not touch the expected conductor layers")
    parents = {node: None for node in sources}
    queue = deque(sources)
    while queue:
        node = queue.popleft()
        if node in targets:
            result = []
            while node is not None:
                result.append((node[0], polygons[node[0]][node[1]].bbox()))
                node = parents[node]
            return list(reversed(result))
        layer, index = node
        current = polygons[layer][index]
        for other in ADJACENT[layer]:
            for j, region in enumerate(polygons[other]):
                candidate = (other, j)
                if candidate in parents or not current.bbox().overlaps(region.bbox()):
                    continue
                # Require positive-area metal/cut overlap, not bounding-box
                # overlap alone. Same-layer shapes were already merged.
                if not (current & region).is_empty():
                    parents[candidate] = node
                    queue.append(candidate)
    return None


def find_instance(top, name, transform):
    matches = [(inst.cell, inst.trans.dup()) for inst in top.each_inst()
               if inst.cell.name == name and str(inst.trans) == transform]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name} instance at {transform}")
    return matches[0]


def find_label(layout, cell, layer, datatype, text):
    layer_index = layout.find_layer(layer, datatype)
    if layer_index is None:
        raise ValueError(f"label layer {layer}/{datatype} missing")
    labels = [shape.text_trans.disp for shape in cell.shapes(layer_index).each()
              if shape.is_text() and shape.text_string.lower() == text.lower()]
    if len(labels) != 1:
        raise ValueError(f"expected one {text!r} label on {cell.name} {layer}/{datatype}")
    return db.Point(labels[0].x, labels[0].y)


def inspect(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED_GDS_SHA256:
        raise ValueError(f"GDS hash differs from run 45835066447: {digest}")
    layout = db.Layout()
    layout.read(str(path))
    top = layout.top_cell()
    if top is None or top.name != "tt_gf_wrapper" or layout.dbu != 0.001:
        raise ValueError("unexpected top cell or GDS database unit")
    sram = find_instance(top, "SP6TSRAM256x32", "r0 508480,3230080")
    logic = find_instance(top, "gf180mcu_fd_sc_mcu7t5v0__mux2_2",
                          "r180 917840,3230080")
    qlocal = find_label(layout, sram[0], 42, 10, "q[22]")
    vlocal = find_label(layout, logic[0], 34, 10, "VSS")
    q = sram[1] * qlocal
    vss = logic[1] * vlocal
    if (q.x, q.y) != (913790, 3237175) or (vss.x, vss.y) != (913640, 3230080):
        raise ValueError(f"unexpected transformed signal or ground label: {q}, {vss}")

    # This witness is entirely inside the box. Clipping cannot manufacture
    # a connection, but it can miss paths that leave and re-enter the box.
    box = db.Box(905000, 3223000, 925000, 3253000)
    regions = {}
    for name, layer in LAYERS.items():
        index = layout.find_layer(layer, 0)
        if index is None:
            raise ValueError(f"GDS layer {layer}/0 missing")
        regions[name] = db.Region(top.begin_shapes_rec_touching(index, box)) & db.Region(box)
    # Explicitly check the narrow root-to-SRAM M3 overlap seen near the
    # SRAM boundary; bounding boxes alone do not establish connectivity.
    m3 = layout.find_layer(42, 0)
    sram_m3 = db.Region(sram[0].begin_shapes_rec(m3)).transformed(sram[1])
    root_m3 = db.Region(top.shapes(m3))
    narrow = (sram_m3 & root_m3 &
              db.Region(db.Box(913920, 3230080, 913930, 3230220)))
    if narrow.area() != 10 * 140:
        raise ValueError(f"expected 10 nm x 140 nm overlap; got {narrow.area()} dbu²")
    q_probe = db.Region(db.Box(q.x - 5, q.y - 5, q.x + 5, q.y + 5))
    vss_probe = db.Region(db.Box(vss.x - 5, vss.y - 5, vss.x + 5, vss.y + 5))
    return path_between(regions, q_probe, vss_probe), layout.dbu


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gds", type=Path)
    args = parser.parse_args()
    try:
        witness, unit = inspect(args.gds)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not witness:
        print("INCONCLUSIVE: expected path not found in the window; this is not sign-off.")
        return 2
    print("FAIL: positive-area drawn-metal/via path from SRAM q[22] to cell VSS:")
    print("  verified SRAM/root M3 overlap: (913.92, 3230.08, 913.93, 3230.22) um")
    for layer, box in witness:
        coordinates = tuple(round(value * unit, 5)
                            for value in (box.left, box.bottom, box.right, box.top))
        print(f"  {layer}: {coordinates} um")
    print("The baseline GDS requires independent foundry DRC/LVS and correction.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
