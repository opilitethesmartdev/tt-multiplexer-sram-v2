#!/usr/bin/env python3
"""Add ANTENNAGATEAREA / ANTENNADIFFAREA to the Arrakeen SRAM LEF.

Areas come from pin_gate_area.py (measured on the macro's own GDS). Without
them OpenROAD cannot see the gates behind the SRAM inputs, so top-level
antenna repair never protects a/d/we/clk.

Usage: python3 lef_add_antenna.py areas.json in.lef > out.lef
SPDX-License-Identifier: Apache-2.0
"""
import json
import re
import sys

areas = json.load(open(sys.argv[1]))
out = []
pin = None
layer = None
for line in open(sys.argv[2]):
	m = re.match(r'\s*PIN\s+(\S+)', line)
	if m:
		pin, layer = m.group(1), None
	if pin and layer is None:
		lm = re.match(r'\s*LAYER\s+(\S+)\s*;', line)
		if lm:
			layer = lm.group(1)
	if pin and re.match(r'\s*ANTENNA(GATE|DIFF)AREA', line):
		continue  # replace any previous values
	if pin and re.match(r'\s*PORT\b', line):
		a = areas.get(pin)
		if a and pin not in ('vdd', 'vss'):
			if a.get('gate', 0) > 0:
				out.append(f'    ANTENNAGATEAREA {a["gate"]:.4f} ;\n')
			if a.get('diff', 0) > 0:
				out.append(f'    ANTENNADIFFAREA {a["diff"]:.4f} ;\n')
	if re.match(r'\s*END\s+(\S+)', line) and pin and line.split()[-1] == pin:
		pin = None
	out.append(line)
sys.stdout.write(''.join(out))
