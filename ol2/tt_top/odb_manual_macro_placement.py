#!/usr/bin/env python3
#
# OpenDB macro placement for the TinyTapeout GF180 top-level flow.
#
# This follows LibreLane's ManualMacroPlacement implementation, but treats
# configured instances absent from the synthesized netlist as optional.
# Every instance that exists in the database is still placed at its configured
# location and orientation.

import sys
from decimal import Decimal

import odb

from reader import click_odb, click


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


# Macros that get a hard placement blockage around them.
#
# The Arrakeen SRAM has all of its signal pins (a/d/we/q, Metal3) starting
# exactly at its bottom edge. With the two banks stacked 7.6um apart, the one
# legal standard-cell row in the gap had its top power rail lying *on*
# sram_lo's bottom edge. StdCellPower then put a Via1-3 stack on that rail,
# and the via pads reach 0.14um into the macro: one landed on q[22] and
# shorted it to vgnd (and others left M2/Via2 spacing errors against the
# macro's column periphery). No via can sit on such a rail without entering
# the macro, so keep the cells (and with them their rails and risers) away.
HALO_MASTERS = {
    "SP6TSRAM256x32": (2.0, 2.0),  # (x, y) halo in um
}


def add_sram_halos(reader):
    dbu = reader.block.getDbUnitsPerMicron()
    n = 0
    for inst in reader.block.getInsts():
        halo = HALO_MASTERS.get(inst.getMaster().getName())
        if halo is None:
            continue
        bb = inst.getBBox()
        hx, hy = int(halo[0] * dbu), int(halo[1] * dbu)
        # A dbBlockage is a hard placement blockage unless marked soft.
        odb.dbBlockage_create(
            reader.block,
            bb.xMin() - hx, bb.yMin() - hy,
            bb.xMax() + hx, bb.yMax() + hy,
        )
        n += 1
        print(f"Placement halo {halo[0]}/{halo[1]}um around {inst.getName()}")
    return n


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

    add_sram_halos(reader)

    missing = sorted(item[0] for item in macros.values())
    if missing:
        print(
            "Skipping configured macro instances absent from the synthesized design:",
            file=sys.stderr,
        )
        for name in missing:
            print(f"* {name}", file=sys.stderr)

    print(f"Successfully placed {placed} macro instances; skipped {len(missing)} absent instances.")


cli.add_command(manual_macro_placement)


if __name__ == "__main__":
    cli()
