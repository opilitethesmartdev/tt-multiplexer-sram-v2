#!/usr/bin/env python3
#
# OpenDB macro placement for the TinyTapeout GF180 top-level flow.
#
# This follows LibreLane's ManualMacroPlacement implementation, but treats
# configured instances absent from the synthesized netlist as optional.
# Every instance that exists in the database is still placed at its configured
# location and orientation.

import os
import sys
from decimal import Decimal

import odb
from reader import click_odb, click
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from routing_safety import placement_halo_strips


@click.group
def cli():
    pass


LEF2OA_MAP = {
    "N": "R0",
    "S": "R180",
    "W": "R90",
    "E": "R270",
    "FN": "MY",
    "FS": "MX",
    "FW": "MXR90",
    "FE": "MYR90",
}


def lef_rot_to_oa_rot(rot):
    if rot in LEF2OA_MAP:
        return LEF2OA_MAP[rot]
    raise ValueError(f"Unsupported macro orientation: {rot}")


def gridify(value, grid):
    return round(value / grid) * grid


def reserve_macro_power_clearance(block, inst):
    """Keep stdcell rows away from hard-macro edges before placement.

    A stdcell supply rail at the exact SRAM boundary previously placed a
    stacked ground via over an SRAM Metal3 signal. The 1 µm placement halo
    provides space for the complete via/riser enclosure and the conservative
    0.3 µm macro clearance checked later. The same issue can occur at
    other macro edges, so this covers every placed hard macro.
    This is not a foundry DRC check.
    """
    if inst.getMaster().getName().startswith(
            ("gf180mcu_fd_sc_", "sky130_fd_sc_", "sg13g2_")):
        return 0
    halo = block.getDbUnitsPerMicron()
    bb = inst.getBBox()
    strips = placement_halo_strips(
        (bb.xMin(), bb.yMin(), bb.xMax(), bb.yMax()), halo)
    for coords in strips:
        if odb.dbBlockage.create(block, *coords) is None:
            raise RuntimeError("failed to create macro placement clearance")
    return len(strips)


@click.command()
@click.option("-c", "--config", required=True, help="Configuration file")
@click.option(
    "-f",
    "--fixed",
    default=False,
    is_flag=True,
    help="Mark placed macros as fixed",
)
@click_odb
def manual_macro_placement(reader, config, fixed):
    db_units_per_micron = reader.block.getDbUnitsPerMicron()

    macros = {}
    with open(config, "r", encoding="utf8") as config_file:
        for line in config_file:
            line = line.split("#")[0].strip()
            if not line:
                continue
            name, x, y, orientation = line.split()
            macros[reader.escape_verilog_name(name)] = [
                name,
                int(Decimal(x) * db_units_per_micron),
                int(Decimal(y) * db_units_per_micron),
                orientation,
            ]

    print("Placing configured macro instances:")
    placed = 0
    clearance_strips = 0
    missing = []

    for inst in reader.block.getInsts():
        inst_name = inst.getName()
        if inst.isFixed():
            if inst_name in macros:
                raise RuntimeError(
                    f"Configured macro {inst_name} is already fixed elsewhere"
                )
            continue

        macro = macros.pop(inst_name, None)
        if macro is None:
            continue

        _, x, y, orientation = macro
        inst.setOrient(lef_rot_to_oa_rot(orientation))
        inst.setLocation(gridify(x, 5), gridify(y, 5))
        inst.setPlacementStatus("FIRM" if fixed else "PLACED")
        placed += 1

    missing = sorted(item[0] for item in macros.values())
    if missing:
        print(
            "Skipping configured macro instances absent from the synthesized design:",
            file=sys.stderr,
        )
        for name in missing:
            print(f"* {name}", file=sys.stderr)

    for inst in reader.block.getInsts():
        if inst.getPlacementStatus() in ("PLACED", "FIRM", "FIXED", "LOCKED"):
            clearance_strips += reserve_macro_power_clearance(reader.block, inst)

    print(f"Successfully placed {placed} macro instances; skipped {len(missing)} absent instances.")
    print(f"Created {clearance_strips} hard-macro placement-clearance strips.")


cli.add_command(manual_macro_placement)


if __name__ == "__main__":
    cli()
