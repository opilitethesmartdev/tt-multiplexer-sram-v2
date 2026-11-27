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


# Hard placement blockage around every hard macro.
#
# A standard-cell row whose boundary coincides with a macro edge has one of
# its power rails lying *on* that edge. No via can be put on such a rail
# without its pads entering the macro, where signal pins start right at the
# boundary: that is how StdCellPower's via stack shorted the SRAM's q[22] to
# vgnd. The same happens at every mux, tile and power-gate edge, so keep
# cells (and with them their rails, taps and risers) 2um away from all of
# them. StdCellPower additionally refuses any via within 0.3um of a macro
# and fails the run if a rail is left unpowered.
MACRO_HALO = (2.0, 2.0)  # (x, y) in um
STDCELL_PREFIX = "gf180mcu_fd_sc_"


def add_macro_halos(reader):
    dbu = reader.block.getDbUnitsPerMicron()
    hx, hy = int(MACRO_HALO[0] * dbu), int(MACRO_HALO[1] * dbu)
    n = 0
    for inst in reader.block.getInsts():
        if inst.getMaster().getName().startswith(STDCELL_PREFIX):
            continue
        if not inst.isPlaced():
            continue
        bb = inst.getBBox()
        # A dbBlockage is a hard placement blockage unless marked soft.
        odb.dbBlockage_create(
            reader.block,
            bb.xMin() - hx, bb.yMin() - hy,
            bb.xMax() + hx, bb.yMax() + hy,
        )
        n += 1
    print(f"Placement halo {MACRO_HALO[0]}/{MACRO_HALO[1]}um around {n} macros")
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

    add_macro_halos(reader)

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
