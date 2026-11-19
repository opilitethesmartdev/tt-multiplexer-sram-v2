#!/usr/bin/env python3

#
# Generate a dummy config for the formal tests filling
# all usable slots with the same module
#
# Copyright (c) 2023 Matt Venn <matt@mattvenn.net>
# Copyright (c) 2023 Sylvain Munaut <tnt@246tNt.com>
# SPDX-License-Identifier: Apache-2.0
#

import argparse

import tt

parser = argparse.ArgumentParser()
parser.add_argument("--module")
args = parser.parse_args()

cfg = tt.TinyTapeout.get_config()

gx = cfg.tt.grid.x
gy = cfg.tt.grid.y

# Muxes reserved for analog switches or huge modules are not instantiated
# in tt_top and therefore cannot host a user module.
reserved = set()
if hasattr(cfg.tt, 'analog'):
	for grp in cfg.tt.analog:
		reserved.update(grp['mux_id'])
if hasattr(cfg.tt, 'huge_modules'):
	reserved.update(cfg.tt.huge_modules.mux_id)

print("modules:")
for mux_id in range(gy):
	if mux_id in reserved:
		continue
	for blk_id in range(gx):
		print(f'  - name: "{args.module}"')
		print(f'    pg_vdd: false')
		print(f'    mux_id: {mux_id}')
		print(f'    blk_id: {blk_id}')
