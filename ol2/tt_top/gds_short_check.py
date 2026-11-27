#!/usr/bin/env python3
#
# Independent metal-short check on the final GF180 GDS.
#
# The LVS path in this flow edits the extracted netlist before netgen sees it
# (well-net merging, supply splitting, port collapsing). Those edits are
# reasonable one by one, but together they can hide a real short: the shared
# SRAM's q[22] was shorted to vgnd by a power via stack and LVS still passed.
#
# This check does not look at any netlist. It extracts connectivity from the
# GDS metal stack (Metal1..Metal5 and the vias between them) with KLayout,
# names nets from the GDS labels, and fails if:
#
#   1. one metal net carries labels of two different supplies
#      (vdpwr/vapwr/vgnd families), i.e. a supply-to-supply short;
#   2. one metal net carries a supply label and a signal label;
#   3. a pin of a hard macro that is not a supply pin (e.g. SRAM q[22],
#      power-gate ctrl, mux um_pg_ena[1]) lands on a supply net.
#
# It does not extract devices, so it cannot see shorts through diffusion or
# a missing via; LVS remains responsible for those.
#
# Usage:
#   klayout -b -r gds_short_check.py -rd gds_in=<gds> -rd report_out=<json>
#   python3 gds_short_check.py <gds> [report.json]   (with the klayout module)
#
# SPDX-License-Identifier: Apache-2.0

import json
import sys

try:
	import pya as db  # inside `klayout -b -r`
except ImportError:  # pragma: no cover - standalone with `pip install klayout`
	import klayout.db as db


# GF180MCU GDS layers: (drawing, label) datatypes per metal, then the vias.
METALS = [(34, 'Metal1'), (36, 'Metal2'), (42, 'Metal3'), (46, 'Metal4'),
	(81, 'Metal5')]
VIAS = [(35, 'Via1'), (38, 'Via2'), (40, 'Via3'), (41, 'Via4')]

SUPPLY_CLASSES = {
	'vdpwr': ('vdpwr', 'vccd', 'vccd1', 'vccd2', 'VDPWR'),
	'vapwr': ('vapwr', 'vdda', 'vdda1', 'vdda2', 'VAPWR'),
	'vgnd':  ('vgnd', 'vssd', 'vssd1', 'vssd2', 'vssa', 'vssa1', 'vssa2',
		'VGND'),
}
SUPPLY_OF = {n: c for c, ns in SUPPLY_CLASSES.items() for n in ns}

# Pin names inside macros / cells that are supplies by definition.
SUPPLY_PIN_NAMES = set(SUPPLY_OF) | {
	'VDD', 'VSS', 'VPWR', 'VNW', 'VPW', 'vdd', 'vss', 'DVDD', 'DVSS',
}
STDCELL_PREFIX = 'gf180mcu_fd_sc_'


def labels(net):
	return [t.strip() for t in (net.name or '').split(',') if t.strip()]


def supply_classes(names):
	return {SUPPLY_OF[n] for n in names if n in SUPPLY_OF}


def check(gds):
	ly = db.Layout()
	ly.read(gds)
	top = ly.top_cell()

	l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(ly, top, []))
	l2n.threads = 4

	stack = []
	for (gl, name), via in zip(METALS, VIAS + [None]):
		m = l2n.make_layer(ly.layer(gl, 0), name)
		stack.append(m)
		for dt in (0, 10):
			t = l2n.make_text_layer(ly.layer(gl, dt), f'{name}.t{dt}')
			l2n.connect(m, t)
		if via is not None:
			stack.append(l2n.make_layer(ly.layer(via[0], 0), via[1]))
	for a, b in zip(stack, stack[1:]):
		l2n.connect(a)
		l2n.connect(a, b)
	l2n.connect(stack[-1])
	l2n.extract_netlist()

	nl = l2n.netlist()
	topc = nl.circuit_by_name(top.name)
	errors = []

	# 1 + 2: labels that meet on one top-level metal net
	for net in topc.each_net():
		names = labels(net)
		cls = supply_classes(names)
		if len(cls) > 1:
			errors.append({'kind': 'supply-short', 'net': names,
				'supplies': sorted(cls)})
		elif cls:
			sig = [n for n in names if n not in SUPPLY_OF]
			if sig:
				errors.append({'kind': 'signal-on-supply', 'supply':
					sorted(cls)[0], 'signals': sig})

	# 3: non-supply macro pins on a supply net
	for sc in topc.each_subcircuit():
		ref = sc.circuit_ref()
		if ref.name.startswith(STDCELL_PREFIX):
			continue
		for pin in ref.each_pin():
			inner = ref.net_for_pin(pin.id())
			outer = sc.net_for_pin(pin.id())
			if inner is None or outer is None or not inner.name:
				continue
			pnames = labels(inner)
			if any(p in SUPPLY_PIN_NAMES for p in pnames):
				continue
			cls = supply_classes(labels(outer))
			if cls:
				errors.append({'kind': 'macro-pin-on-supply',
					'cell': ref.name, 'instance': sc.expanded_name(),
					'pin': pnames, 'supply': sorted(cls)})

	return errors


def main():
	# `klayout -b -r ... -rd gds_in=... -rd report_out=...` defines globals.
	gds = globals().get('gds_in')
	report = globals().get('report_out')
	if gds is None:
		gds = sys.argv[1]
		report = sys.argv[2] if len(sys.argv) > 2 else None

	errors = check(gds)
	if report:
		with open(report, 'w', encoding='utf-8') as f:
			json.dump({'errors': errors}, f, indent=1)
	for e in errors:
		print('GDS SHORT:', json.dumps(e))
	print(f'gds_short_check: {len(errors)} short(s) in {gds}')
	if errors:
		sys.exit(1)


main()
