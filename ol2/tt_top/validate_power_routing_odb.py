#!/usr/bin/env python3
"""Partial local OpenROAD replay for SRAM placement and power-routing fixes.

This accepts the baseline's post-detailed-placement ODB, adds the same SRAM
placement halos, re-legalizes cells, and runs WellTaps, StdCellPower, and
MacroPowerVias. It deliberately does not run ModulePowerStrapper, global or
detailed signal routing, GDS streamout, DRC, LVS, or SPICE. Success is not
evidence that the final chip is safe. Run using an OpenROAD Python wheel.
"""
import argparse
import importlib.util
from pathlib import Path
import sys
import types

import odb
import openroad

from routing_safety import blocked_by_macro, blocked_by_other_pin, placement_halo_strips


def load_routing_module():
    # These imports are used by other parts of odb_route, not the three
    # classes being replayed. Avoid requiring a configured shuttle checkout.
    for name in ("yaml", "tt", "tt_odb", "reader", "click"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    sys.modules["reader"].click_odb = lambda f: f
    sys.modules["click"].command = lambda *args, **kwargs: lambda f: f
    path = Path(__file__).with_name("odb_route.py")
    spec = importlib.util.spec_from_file_location("_power_replay_route", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def box(obj):
    return (obj.xMin(), obj.yMin(), obj.xMax(), obj.yMax())


def check_standard_vias(reader, power):
    """Check newly-generated standard-cell via stacks against macro bboxes."""
    count = 0
    for name in power.NETS:
        net = reader.block.findNet(name)
        if net is None:
            continue
        for swire in net.getSWires():
            for wire in swire.getWires():
                via = wire.getBlockVia() if wire.isVia() else None
                if via is None or not via.getName().startswith("tt_Via"):
                    continue
                count += 1
                if blocked_by_macro(box(wire), power.macros, power.macro_clearance):
                    raise RuntimeError(f"standard-cell via {via.getName()} near a macro")
    if count == 0:
        raise RuntimeError("no generated standard-cell vias were checked")
    print(f"Checked {count} generated standard-cell via boxes against macro halos.")


def check_gate_control(reader):
    """Check gate ctrl LEF rectangles against foreign power special wires."""
    count = 0
    for inst in reader.block.getInsts():
        if not inst.getMaster().getName().startswith("tt_pg_"):
            continue
        ctrl = next((it for it in inst.getITerms()
                     if it.getMTerm().getName() == "ctrl"), None)
        if ctrl is None:
            raise RuntimeError("power gate has no ctrl pin")
        signal_net = ctrl.getNet()
        signal_name = signal_net.getName() if signal_net else None
        rects = [box(r) for layer, r in ctrl.getGeometries()
                 if hasattr(layer, "getName") and layer.getName() == "Metal4"]
        if not rects:
            raise RuntimeError("power gate ctrl has no Metal4 shape")
        obstacles = []
        for net in reader.block.getNets():
            if net.getName() == signal_name:
                continue
            for swire in net.getSWires():
                for wire in swire.getWires():
                    if wire.isVia() or wire.getTechLayer().getName() == "Metal4":
                        obstacles.append((net.getName(), box(wire)))
        if blocked_by_other_pin(rects, signal_name, obstacles, 0):
            raise RuntimeError(f"{inst.getName()} ctrl touches a foreign special wire")
        count += 1
    if not count:
        raise RuntimeError("no power gates found")
    print(f"Checked {count} power-gate control pins against foreign special wires.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_odb", type=Path)
    parser.add_argument("--output-odb", type=Path)
    parser.add_argument("--check-gates-only", action="store_true",
                        help="audit existing special wires without changing placement")
    args = parser.parse_args()
    if args.output_odb and args.output_odb.exists():
        parser.error("refusing to overwrite output ODB")
    route = load_routing_module()
    tech = openroad.Tech()
    design = openroad.Design(tech)
    design.readDb(str(args.input_odb))
    reader = types.SimpleNamespace(db=design.getDb(), block=design.getBlock())
    if reader.block.getName() != "tt_gf_wrapper":
        raise ValueError("unexpected top block")
    if args.check_gates_only:
        check_gate_control(reader)
        return
    srams = [inst for inst in reader.block.getInsts()
             if inst.getMaster().getName() == "SP6TSRAM256x32"]
    if len(srams) != 2:
        raise ValueError(f"expected two SRAMs, found {len(srams)}")
    halo = reader.block.getDbUnitsPerMicron()
    for inst in srams:
        for rect in placement_halo_strips(box(inst.getBBox()), halo):
            if odb.dbBlockage.create(reader.block, *rect) is None:
                raise RuntimeError("cannot create placement halo")
    design.evalTclString("detailed_placement")
    design.evalTclString("check_placement -verbose")
    route.WellTaps(reader).run()
    power = route.StdCellPower(reader)
    power.run()
    check_standard_vias(reader, power)
    route.MacroPowerVias(reader).run()
    check_gate_control(reader)
    if args.output_odb:
        design.writeDb(str(args.output_odb))
        print(f"Wrote partial replay database {args.output_odb}")
    print("Partial replay passed; full routed GDS and independent DRC/LVS remain required.")


if __name__ == "__main__":
    main()
