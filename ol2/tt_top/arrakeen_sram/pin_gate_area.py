#!/usr/bin/env python3
"""Measure the transistor gate area behind each SRAM pin, from the GDS.

The Arrakeen generator writes a LEF without ANTENNAGATEAREA, so OpenROAD's
antenna checker sees no gates behind the macro's inputs and the top-level
repair never protects them (the foundry antenna deck then flags the long
top-level wires into a/d/we/clk). This traces Metal3 -> ... -> Metal1 ->
poly contacts -> poly for every labelled pin and reports the area of poly
over COMP (the gate) and the source/drain diffusion on that net.

Usage: python3 pin_gate_area.py SP6TSRAM256x32.gds > gate_areas.json
SPDX-License-Identifier: Apache-2.0
"""
import json
import sys

import klayout.db as db

gds = sys.argv[1]
ly = db.Layout()
ly.read(gds)
top = ly.top_cell()
l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(ly, top, []))

comp = l2n.make_layer(ly.layer(22, 0), 'comp')
poly = l2n.make_layer(ly.layer(30, 0), 'poly')
cont = l2n.make_layer(ly.layer(33, 0), 'cont')
m1 = l2n.make_layer(ly.layer(34, 0), 'm1')
v1 = l2n.make_layer(ly.layer(35, 0), 'v1')
m2 = l2n.make_layer(ly.layer(36, 0), 'm2')
v2 = l2n.make_layer(ly.layer(38, 0), 'v2')
m3 = l2n.make_layer(ly.layer(42, 0), 'm3')
t2 = l2n.make_text_layer(ly.layer(36, 10), 't2')
t3 = l2n.make_text_layer(ly.layer(42, 10), 't3')

# Only contacts that land on poly join a net to poly; diffusion contacts
# are source/drain, not gate, and must not merge nets through the channel.
cont_poly = cont & poly
gate = poly & comp
# Source/drain diffusion: COMP minus the gates, so each S/D island is its
# own shape and nothing merges through a channel.
diff = comp - poly
cont_diff = cont & diff

for a, b in ((m3, v2), (v2, m2), (m2, v1), (v1, m1), (m1, cont_poly),
		(cont_poly, poly)):
	l2n.connect(a)
	l2n.connect(a, b)
l2n.connect(poly)
l2n.connect(gate)
l2n.connect(poly, gate)
l2n.connect(cont_diff)
l2n.connect(m1, cont_diff)
l2n.connect(diff)
l2n.connect(cont_diff, diff)
l2n.connect(m3, t3)
l2n.connect(m2, t2)
l2n.extract_netlist()

circ = l2n.netlist().circuit_by_name(top.name)
out = {}
for net in circ.each_net():
	names = [n.strip() for n in (net.name or '').split(',') if n.strip()]
	if not names:
		continue
	g = l2n.shapes_of_net(net, gate, True)
	g.merge()
	d = l2n.shapes_of_net(net, diff, True)
	d.merge()
	for n in names:
		out[n] = {'gate': round(g.area() * ly.dbu * ly.dbu, 4),
			'diff': round(d.area() * ly.dbu * ly.dbu, 4)}

json.dump(out, sys.stdout, indent=1, sort_keys=True)
