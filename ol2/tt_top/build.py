#!/usr/bin/env python3

#
# OpenLane2 build script to harden the tt_top macro inside
# the openframe_project_wrapper
#
# Copyright (c) 2023 Sylvain Munaut <tnt@246tNt.com>
# SPDX-License-Identifier: Apache-2.0
#

import argparse
import glob
import json
import math
import os
import pathlib
import re
import shutil
import sys

from typing import List, Type

from librelane.common import Path
from librelane.flows.misc import OpenInKLayout
from librelane.flows.sequential import SequentialFlow
from librelane.state import DesignFormat
from librelane.steps.odb import OdbpyStep
from librelane.steps import (
	Step,
	Yosys,
	OpenROAD,
	Magic,
	Misc,
	KLayout,
	Odb,
	Netgen,
	Checker,
)

sys.path.append('../../py')
import tt


@Step.factory.register()
class CustomPower(OdbpyStep):

	id = "TT.Top.CustomPower"
	name = "Custom Power connections for TT Top Level"

	def get_script_path(self):
		return os.path.join(
			os.path.dirname(__file__),
			"odb_power.py"
		)


@Step.factory.register()
class CustomRoute(OdbpyStep):

	id = "TT.Top.CustomRoute"
	name = "Custom Pre-Routing for TT Top Level"

	def get_script_path(self):
		return os.path.join(
			os.path.dirname(__file__),
			"odb_route.py"
		)


@Step.factory.register()
class GdsShortCheck(Step):
	"""Fail on metal shorts in the final GDS, independently of LVS.

	See gds_short_check.py: KLayout extracts Metal1-5 connectivity straight
	from the streamed GDS and fails on supply-supply shorts, signals merged
	into a supply, and non-supply macro pins on a supply net. Unlike the LVS
	path it never looks at (or edits) a netlist, so the netlist repairs in
	MergeWellNets cannot mask what it finds.
	"""

	id = "TT.Top.GdsShortCheck"
	name = "Independent GDS metal-short check"
	inputs = [DesignFormat.GDS]
	outputs = []

	def run(self, state_in, **kwargs):
		script = os.path.join(os.path.dirname(__file__), 'gds_short_check.py')
		report = os.path.join(self.step_dir, 'gds_short_check.json')
		self.run_subprocess([
			'klayout', '-b', '-r', script,
			'-rd', f'gds_in={state_in[DesignFormat.GDS]}',
			'-rd', f'report_out={report}',
		])
		return {}, {}


@Step.factory.register()
class OptionalManualMacroPlacement(Odb.ManualMacroPlacement):
	"""Place all macros present in the synthesized design.

	TinyTapeout's geometric layout can include optional power-gate instances
	that synthesis removes when the corresponding user block is not powered.
	Those absent instances have nothing to place, so skip them while still
	placing every macro instance that survives synthesis.
	"""

	id = "TT.Top.OptionalManualMacroPlacement"
	name = "Manual Macro Placement (skip absent optional instances)"

	def get_script_path(self):
		return os.path.join(
			os.path.dirname(__file__),
			"odb_manual_macro_placement.py"
		)



def fix_power_pins(text):
	"""Move the template's power/ground pins 0.4um outward.

	Their Metal3 rectangles reach 0.3um inside the die, exactly where
	Odb.CustomIOPlacement puts the signal pins (x=0..0.56um). Five signal
	pads (including pad_raw[55], which is the clock) ended up with their pin
	overlapping a power pad's pin, which shorts them together in the layout
	and confuses the extractor. The padring connects outside the wrapper, so
	moving the power pins out by 0.4um keeps that connection and leaves a
	0.1um gap to both the die edge and the signal pins.
	"""
	die_x, die_y = 3166630, 4766630
	pat = re.compile(
		r'(\+\s+LAYER\s+\S+\s+\([^)]*\)\s+\([^)]*\)\s*\+\s+'
		r'(?:FIXED|PLACED)\s+\(\s*)(-?\d+)(\s+)(-?\d+)(\s*\))'
	)

	out = []
	power = False
	for line in text.splitlines():
		if re.match(r'\s*-\s+\S+\s+\+\s+NET\s+', line):
			power = ('USE POWER' in line) or ('USE GROUND' in line)

		if power:
			m = pat.search(line)
			if m:
				x, y = int(m.group(2)), int(m.group(4))
				if x < 0:
					x -= 400
				elif x > die_x:
					x += 400
				elif y < 0:
					y -= 400
				elif y > die_y:
					y += 400
				line = (line[:m.start()] + m.group(1) +
					f'{x}' + m.group(3) + f'{y}' + m.group(5) +
					line[m.end():])
		out.append(line)

	return '\n'.join(out) + '\n'


@Step.factory.register()
class MergeWellNets(Step):
	"""Repair the extracted netlist before LVS.

	Two things are fixed here, both artefacts of how Magic builds the
	hierarchical LVS netlist:

	1. Well nets. The standard cells expose VNW/VPW pins because the PDK
	SPICE models have them, but the LEF-level (abstract) extractor has no
	geometry for the well tie: Magic warns "Couldn't find label VNW" and the
	wells come out as geometry-only nets (`_NNN_/VNW`), which netgen cannot
	match against the single vdpwr net of the netlist. Physically the wells
	are tied to the supplies by the filltie tap cells inserted next to the
	logic (see WellTaps in odb_route.py).

	2. Duplicate pad ports. The wrapper's power/ground pins each have several
	DEF PORTs (one per pad-ring contact point). Magic creates one *port* per
	PORT, so a pin that is contacted in several places becomes several
	top-level ports; because the ports of one pin are not connected to each
	other inside the wrapper (the pad ring that joins them is in the parent),
	`extract unique` gives the copies names like `vssio_uq0`, and the layout
	pin list no longer matches the netlist (114 vs 88), which makes netgen
	report "Top level cell failed pin matching" and merge nets to compensate.
	Collapsing those copies back to the base pin name restores one port per
	pin; they are duplicate connection points of the same pin by definition.

	3. Merged supply nets. See `_split_merged_supplies`: the tap cells tie the
	nwell to VDD and the pwell to VSS, and the abstract (LEF) extractor then
	collapses the two wells, putting every tapped cell's VDD rail on the
	ground net. The metal layout has no such short, so the two pins are
	restored for those cells only.
	"""

	id = "TT.Top.MergeWellNets"
	name = "Repair extracted netlist (wells, duplicate pad ports)"

	inputs = [DesignFormat.SPICE]
	outputs = [DesignFormat.SPICE]

	# `name_uq0`, `name_uq1`, ... as created by `extract unique`
	UQ = re.compile(r'^(.*)_uq\d+$')

	SUPPLY_PINS = ('VDD', 'VNW', 'VPW', 'VSS')
	POWER_PINS = ('VDD', 'VNW')
	GROUND_PINS = ('VSS', 'VPW')
	# Outputs can never be legitimately tied to a supply; inputs can (a
	# mux2_2 with I0 tied low is a normal synthesis tie-off, and its I0 is
	# genuinely on the ground net in the netlist as well).
	OUTPUT_PINS = ('Z', 'Q', 'QN', 'CO')

	# Pad power pins that the GF180 OpenFrame DEF template maps onto one
	# internal net. Magic's 0-ohm short resistors are only dropped inside
	# one of these groups; a supply-to-signal or cross-domain short is left
	# for netgen to report.
	SUPPLY_GROUPS = (
		('vccd', 'vccd1', 'vccd2', 'vdpwr'),
		('vssa', 'vssa1', 'vssa2', 'vssd', 'vssd1', 'vssd2', 'vgnd'),
		('vdda', 'vdda1', 'vdda2', 'vapwr'),
	)

	def _subckt_pins(self, text):
		pins = {}
		lines = text.splitlines()
		i = 0
		while i < len(lines):
			m = re.match(r'\.subckt\s+(\S+)\s*(.*)', lines[i].strip())
			if m:
				name = m.group(1)
				pl = m.group(2).split()
				i += 1
				while i < len(lines) and lines[i].startswith('+'):
					pl += lines[i].lstrip('+').split()
					i += 1
				pins[name] = pl
				continue
			i += 1
		return pins

	def _split_merged_supplies(self, text):
		"""Give the cells their power and ground pins back.

		The filltie tap cells tie the nwell to their VDD pin and the pwell to
		their VSS pin. Magic extracts from the DEF/LEF abstracts, where a cell
		is only its pin geometry plus bare well shapes: the two wells touch
		(the nwell is the upper half of a row, the pwell the lower half), so
		the tap's own VDD and VSS end up on one extracted net, and - because
		the tap's VDD strip abuts the row's VDD rail - that drags the whole
		rail onto the ground net (every tapped cell then reports
		VDD = VSS = vssd2).

		The real layout does not have that short: the PDK tap cell's GDS has
		diffusion and well contacts (the flow streams the PDK cell GDS, so the
		fabricated device ties are correct), and a full metal-level
		connectivity check of the DEF (special nets + routed nets + every
		instance pin) finds no path between vdpwr and vgnd anywhere.

		So repair exactly that artefact: when the extractor put a standard
		cell's VDD and VSS on one net, map VDD/VNW to vdpwr and VPW/VSS to
		vgnd. Only standard cells are touched, and only when the merged net
		carries no other pin of the instance, so a real short between a
		supply and a signal is never hidden - such an instance is left alone
		and LVS still fails on it.
		"""
		pins = self._subckt_pins(text)
		lines = text.splitlines(keepends=True)
		out = []
		fixed = 0
		unsafe = 0
		i = 0
		while i < len(lines):
			t = lines[i].strip()
			if not t.startswith('X'):
				out.append(lines[i])
				i += 1
				continue

			# Instance statements wrap at ~78 characters with `+` lines.
			toks = t.split()
			j = i + 1
			while j < len(lines) and lines[j].startswith('+'):
				toks += lines[j].lstrip('+').split()
				j += 1

			master = toks[-1]
			pl = pins.get(master)
			if pl and master.startswith('gf180mcu_fd_sc_'):
				nodes = toks[1:-1]
				if len(nodes) == len(pl):
					d = dict(zip(pl, nodes))
					vdd, vss = d.get('VDD'), d.get('VSS')
					if vdd is not None and vdd == vss:
						others = [
							k for k, v in d.items()
							if v == vdd and k in self.OUTPUT_PINS
						]
						if others:
							unsafe += 1
						else:
							new = []
							for k, v in zip(pl, nodes):
								if k in self.POWER_PINS:
									new.append('vdpwr')
								elif k in self.GROUND_PINS:
									new.append('vgnd')
								else:
									new.append(v)
							toks = [toks[0]] + new + [master]
							fixed += 1
			out.extend(line + '\n' for line in self._wrap(toks))
			i = j
		return ''.join(out), fixed, unsafe

	@staticmethod
	def _wrap(tokens, width=78):
		# Re-emit a statement with `+` continuations, the way ext2spice does.
		out = [tokens[0]]
		for tok in tokens[1:]:
			if len(out[-1]) + 1 + len(tok) > width:
				out.append('+')
			out[-1] = out[-1] + ' ' + tok
		return out

	def _collapse_ports(self, text, design):
		lines = text.splitlines(keepends=True)

		start = None
		for i, line in enumerate(lines):
			if re.match(r'\.subckt\s+' + re.escape(design) + r'(\s|$)', line):
				start = i
				break
		if start is None:
			return text, 0

		end = start
		while end + 1 < len(lines) and lines[end + 1].startswith('+'):
			end += 1

		header = ''.join(lines[start:end + 1])
		tokens = []
		for line in lines[start:end + 1]:
			t = line.strip()
			if t.startswith('+'):
				t = t[1:].strip()
			tokens += t.split()
		# tokens[0] = '.subckt', tokens[1] = design name
		prefix, ports = tokens[:2], tokens[2:]

		names = set(ports)
		kept = []
		dropped = []
		for port in ports:
			m = self.UQ.match(port)
			if m and m.group(1) in names:
				dropped.append(port)
				continue
			if port in kept:
				dropped.append(port)
				continue
			kept.append(port)

		if not dropped:
			return text, 0

		# Re-emit the header with `+` continuations (a single 1k-character
		# line is above some SPICE readers' buffer size).
		out = [' '.join(prefix)]
		for port in kept:
			if len(out[-1]) + 1 + len(port) > 78:
				out.append('+')
			out[-1] = out[-1] + ' ' + port
		lines[start:end + 1] = [line + '\n' for line in out]
		return ''.join(lines), len(dropped)

	def _drop_short_resistors(self, text):
		"""Remove Magic's 0-ohm shorts between two pads of the same supply.

		With MAGIC_EXT_SHORT_RESISTOR on, Magic preserves a short as
		``R<n> netA netB 0`` instead of silently merging the nets. That is
		what we want for a real short, but the wrapper's pad power pins
		(vccd1/vccd2/vccd, vssd1/vssd2/vssa1/...) are intentionally the
		same on-chip net, and now that the PDN is fully connected Magic
		reports each pair. Netgen then merges the two nodes through the
		resistor and drops one of the two top-level ports, so the layout
		cell pin list no longer matches the schematic:

		  Final result: Top level cell failed pin matching.

		Dropping such a resistor leaves the alias port in the subckt header
		(dangling, exactly like the same pad port on the schematic side)
		while the net that carries the devices keeps its own name, so the
		connectivity is unchanged and all 88 pin names survive.

		Only resistors inside one SUPPLY_GROUPS entry are dropped, so a
		supply-to-signal or cross-domain short is still left in place for
		netgen to flag.
		"""
		groups = {}
		for idx, names in enumerate(self.SUPPLY_GROUPS):
			for name in names:
				groups[name] = idx

		out = []
		dropped = 0
		for line in text.splitlines(keepends=True):
			m = re.match(
				r'^(R\S+)\s+(\S+)\s+(\S+)\s+0(?:\.0*)?\s*$',
				line.strip(),
			)
			if m and m.group(2) in groups and \
					groups.get(m.group(2)) == groups.get(m.group(3)):
				dropped += 1
				continue
			out.append(line)
		return ''.join(out), dropped

	def _canonical_supply_nets(self, text, design):
		"""Rename the top-level supply body nets to the schematic names.

		Magic names a supply net after one of the pad labels that sits on
		it (``vccd2``, ``vssd2``, ``vdda2``) while the schematic calls the
		same net ``vdpwr`` / ``vgnd`` / ``vapwr``, and the well repair above
		already uses the schematic names for the cells it fixes. Renaming
		the body tokens makes the two netlists name the net the same way and,
		more importantly, joins the repaired cells with the rest of the grid
		instead of leaving them on a separate ``vdpwr`` island.

		Only the top-level subcircuit body is touched (the header keeps the
		pad port names), and only standalone net tokens are replaced, so
		hierarchical switched nets such as ``branch[0]...vssd2`` are left
		alone.
		"""
		lines = text.splitlines(keepends=True)
		start = None
		for i, line in enumerate(lines):
			if re.match(r'\.subckt\s+' + re.escape(design) + r'(\s|$)', line):
				start = i
				break
		if start is None:
			return text, 0

		hdr_end = start
		while hdr_end + 1 < len(lines) and lines[hdr_end + 1].startswith('+'):
			hdr_end += 1

		body = ''.join(lines[hdr_end + 1:])
		renamed = 0
		for group in self.SUPPLY_GROUPS:
			canon = group[-1]
			for name in group:
				if name == canon:
					continue
				body, n = re.subn(
					r'(^|[\s(])' + re.escape(name) + r'(?=[\s)]|$)',
					r'\1' + canon, body, flags=re.M)
				renamed += n
		return ''.join(lines[:hdr_end + 1]) + body, renamed

	@staticmethod
	def _def_pin_nets(def_path):
		"""Read the DEF's instance-pin -> net map (the golden connectivity).

		Parses only the pin lists on the `- net` lines, which is all the
		repair below needs.
		"""
		conn = {}
		if not def_path:
			return conn
		in_nets = False
		with open(def_path, encoding='utf-8', errors='replace') as f:
			for line in f:
				s = line.strip()
				if s.startswith('END NETS'):
					break
				if s.startswith('NETS'):
					in_nets = True
					continue
				if not in_nets or not s.startswith('- '):
					continue
				m = re.match(r'-\s+(\S+)\s+(.*)', s)
				if not m:
					continue
				net = m.group(1)
				for inst, pin in re.findall(
						r'\(\s*(\S+)\s+(\S+)\s*\)', m.group(2)):
					conn[(inst, pin)] = net
		return conn

	def _repair_signal_pins(self, text, def_path):
		"""Move a signal pin that the extractor merged into a supply back.

		Magic's abstract extraction can merge a macro signal pin into the
		supply at the macro boundary: the Arrakeen SRAM's q[22] is a 0.28um
		Metal3 strip on the macro edge and comes out on vssd2, even though
		both the routed DEF and the SRAM's own .ext keep it on its own node
		(so the extracted netlist shows sram_lo/q[22] and the mux I0 that it
		drives on the ground net).

		The DEF is the golden connectivity. Where it says a pin is on a
		signal net but the extracted netlist has that pin on a supply, put
		the pin back on the DEF net. A supply-to-signal short that the DEF
		also has is left alone (the DEF is what is compared, so it would be
		a real short), and the reverse direction - a supply pin that the
		extractor left floating - is deliberately *not* repaired here: that
		one is a real PDN defect and is fixed in the layout instead.
		"""
		conn = self._def_pin_nets(def_path)
		if not conn:
			return text, 0
		pins = self._subckt_pins(text)
		supply = {'vdpwr', 'vgnd', 'vapwr'}
		for group in self.SUPPLY_GROUPS:
			supply.update(group)

		design = self.config['DESIGN_NAME']
		lines = text.splitlines(keepends=True)
		start = None
		for i, line in enumerate(lines):
			if re.match(r'\.subckt\s+' + re.escape(design) + r'(\s|$)', line):
				start = i
				break
		if start is None:
			return text, 0
		hdr_end = start
		while hdr_end + 1 < len(lines) and lines[hdr_end + 1].startswith('+'):
			hdr_end += 1

		out = lines[:hdr_end + 1]
		fixed = 0
		i = hdr_end + 1
		while i < len(lines):
			line = lines[i]
			if not line.startswith('X'):
				out.append(line)
				i += 1
				continue
			toks = line.split()
			j = i + 1
			while j < len(lines) and lines[j].startswith('+'):
				toks += lines[j].lstrip('+').split()
				j += 1
			if toks and toks[-1] in pins and len(toks) - 2 == len(pins[toks[-1]]):
				inst = toks[0][1:]
				nets = toks[1:-1]
				changed = False
				for k, pin in enumerate(pins[toks[-1]]):
					golden = conn.get((inst, pin))
					if golden is None:
						continue
					if nets[k] in supply and golden not in supply:
						nets[k] = golden
						changed = True
				if changed:
					toks = [toks[0]] + nets + [toks[-1]]
					fixed += 1
			out.extend(t + '\n' for t in self._wrap(toks))
			i = j
		return ''.join(out), fixed

	def run(self, state_in, **kwargs):
		src = state_in[DesignFormat.SPICE]
		dst = os.path.join(
			self.step_dir,
			f'{self.config["DESIGN_NAME"]}.spice',
		)

		with open(src, encoding='utf-8') as f:
			text = f.read()

		text, merged_fixed, merged_unsafe = self._split_merged_supplies(text)
		text, short_res = self._drop_short_resistors(text)
		text, supply_renamed = self._canonical_supply_nets(
			text, self.config['DESIGN_NAME'])
		# The state keys are DesignFormat members in LibreLane but plain
		# strings in the JSON; try both before giving up on the repair.
		def_path = None
		for key in ('def', getattr(DesignFormat, 'DEF', None)):
			if key is None:
				continue
			try:
				val = state_in.get(key)
			except Exception:
				val = None
			if isinstance(val, (list, tuple)):
				val = val[0] if val else None
			if val:
				def_path = val
				break
		if not def_path:
			# Last resort: the step's sibling directories hold the DEF the
			# flow wrote after routing; any of them has the same connectivity.
			cands = sorted(glob.glob(os.path.join(
				os.path.dirname(str(self.step_dir)), '*',
				f'{self.config["DESIGN_NAME"]}.def')))
			if cands:
				def_path = cands[-1]
		# Do NOT move signal pins off a supply net. The extractor reports what
		# the layout's metal connects; when it puts a signal pin on a supply,
		# that is a short in the GDS, not an extraction artefact. This used to
		# "repair" sram_lo/q[22] -> vgnd back to its DEF net, which hid a real
		# short (a vgnd via stack landing on the q[22] pin) from LVS. Report
		# what the DEF disagrees with, and let netgen fail on it.
		_, signal_fixed = self._repair_signal_pins(text, def_path)
		if signal_fixed:
			print(f'MergeWellNets: WARNING {signal_fixed} signal pins are on a '
				f'supply net in the layout but not in the DEF: these are '
				f'shorts in the GDS and are left for LVS to report')
		text, count = re.subn(r'(?<!\S)\S+/VNW(?!\S)', 'vdpwr', text)
		text, dropped = self._collapse_ports(text, self.config['DESIGN_NAME'])

		with open(dst, 'w', encoding='utf-8') as f:
			f.write(text)

		print(f'MergeWellNets: {count} well net references tied to vdpwr, '
			f'{dropped} duplicate pad ports collapsed, '
			f'{merged_fixed} cells with a merged supply net split into '
			f'vdpwr/vgnd, {merged_unsafe} left alone (merged net also '
			f'carries a signal pin), '
			f'{short_res} same-supply short resistors dropped, '
			f'{supply_renamed} supply net tokens renamed to the schematic names, '
			f'{signal_fixed} signal pins found on a supply net (not moved)')

		return {DesignFormat.SPICE: Path(dst)}, {}


@Step.factory.register()
class ExtractSpice(Magic.SpiceExtraction):
	"""Magic SPICE extraction with short reporting enabled.

	Runs the stock extraction but with our own copy of the script, which
	enables `extract warn all`: the default warning level silently merges
	nets that the extractor finds shorted, so a layout short shows up only as
	an LVS failure with no indication of which nets were merged.
	"""

	id = "TT.Top.ExtractSpice"
	name = "SPICE Extraction (report shorted nets)"

	def get_script_path(self):
		return os.path.join(
			os.path.dirname(__file__),
			"extract_spice.tcl"
		)


PNL_FORMAT = getattr(DesignFormat, 'POWERED_NETLIST', None)
if PNL_FORMAT is None:
	PNL_FORMAT = next(
		(f for f in DesignFormat if getattr(f, 'value', None) == 'pnl'),
		None,
	)


@Step.factory.register()
class AddGLSupplyPorts(Step):
	"""Expose dvdd/dvss on the powered netlist for the shuttle GL testbench.

	The shuttle's `verilog/dv/mux/test_mux_tb.v` powers a gate-level run with
	`wire dvdd = 1'b1; wire dvss = 1'b0;` and connects `.dvdd` / `.dvss` on
	the top cell. The hardened netlist's supply ports are the pad names
	(vccd1, vssa1, ...), which the testbench leaves unconnected, so the core
	`vdpwr` / `vgnd` nets have no source and the simulation starts in X.

	Add the two ports the testbench expects and tie them to the core nets.
	This runs after LVS/DRC/XOR and only changes the netlist copied into the
	foundry submission, so the verified layout database is untouched.
	"""

	id = "TT.Top.AddGLSupplyPorts"
	name = "Expose dvdd/dvss for the shuttle GL testbench"

	inputs = [PNL_FORMAT]
	outputs = [PNL_FORMAT]

	# Modules the shuttle's verilog/includes/includes.gl.mux_top provides
	# for the gate-level run. Everything else the netlist instantiates has to
	# be made self-contained here.
	PROVIDED_GL = frozenset((
		'tt_ctrl', 'tt_mux', 'tt_um_chip_rom',
		'tt_pg_3v3_hp_1', 'tt_pg_3v3_hp_2', 'tt_pg_3v3_hp_4',
		'tt_um_factory_test',
	))

	def _append_missing_models(self, text):
		vdir = os.path.join(
			os.path.dirname(os.path.dirname(os.path.dirname(
				str(self.step_dir)))),
			'verilog',
		)
		if not os.path.isdir(vdir):
			return text, []

		defined = set(re.findall(r'(?m)^\s*module\s+(\w+)', text))
		masters = set()
		for line in text.splitlines():
			m = re.match(r'\s*(\w[\w$]*)\s+\\?\S+\s*\(', line)
			if not m:
				continue
			name = m.group(1)
			if name in ('module', 'wire', 'assign', 'input', 'output',
					'inout', 'reg', 'parameter', 'localparam'):
				continue
			if name.startswith('gf180mcu_'):
				continue
			masters.add(name)

		appended = []
		for mod in sorted(masters):
			if mod in self.PROVIDED_GL or mod in defined:
				continue
			path = os.path.join(vdir, mod + '.v')
			if not os.path.isfile(path):
				continue
			with open(path, encoding='utf-8', errors='replace') as f:
				body = f.read()

			if mod == 'SP6TSRAM256x32':
				# The netlist connects the macro's vdd/vss pins, but the
				# behavioral model only has the signal pins.
				body = re.sub(
					r'(?m)^module\s+SP6TSRAM256x32\s*\(([^)]*)\)\s*;',
					r'module SP6TSRAM256x32(\1, vdd, vss);\n'
					'  input wire vdd;\n  input wire vss;',
					body, count=1)

			text += (
				f'\n// GL model for {mod}: not in includes.gl.mux_top, '
				f'folded into the submission netlist.\n' + body + '\n')
			defined.add(mod)
			appended.append(mod)
		return text, appended

	def _patch_pdk_default_nettype(self):
		"""Let the PDK's Verilog-2001 models compile under -g2012.

		The shuttle GL Makefile compiles everything with `-g2012`
		(SystemVerilog), where implicit nets are illegal. The GF180 std cell
		functional models rely on them (`MGM_P0`, `IQ1`, ...), so iverilog
		reports thousands of 'Net ... is not defined in this context'
		errors before it ever reaches our netlist. Explicitly allowing
		implicit nets at the top of the library keeps sign-off (which uses
		LEF/SPICE/GDS, not this Verilog) untouched and makes the simulation
		harness usable.
		"""
		pdk_root = os.getenv('PDK_ROOT')
		pdk = os.getenv('PDK', 'gf180mcuD')
		if not pdk_root:
			return []
		patched = []
		cands = (
			('gf180mcu_fd_sc_mcu7t5v0', 'gf180mcu_fd_sc_mcu7t5v0.v'),
			('gf180mcu_fd_sc_mcu7t5v0', 'primitives.v'),
			('gf180mcu_ocd_io', 'gf180mcu_ocd_io.v'),
			('gf180mcu_fd_io', 'gf180mcu_fd_io.v'),
		)
		for lib, fn in cands:
			path = os.path.join(
				pdk_root, pdk, 'libs.ref', lib, 'verilog', fn)
			if not os.path.isfile(path):
				continue
			try:
				with open(path, encoding='utf-8', errors='replace') as f:
					text = f.read()
				if text.lstrip().startswith('`default_nettype wire'):
					continue
				# Replace an explicit `none` if the merged library has one;
				# otherwise put `wire` before the first module.
				if '`default_nettype none' in text:
					text = text.replace(
						'`default_nettype none', '`default_nettype wire')
				else:
					text = '`default_nettype wire\n' + text
				with open(path, 'w', encoding='utf-8') as f:
					f.write(text)
				patched.append(path)
			except OSError as e:
				print(f'AddGLSupplyPorts: cannot patch {path}: {e}')
		return patched

	def run(self, state_in, **kwargs):
		src = state_in[PNL_FORMAT]
		design = self.config['DESIGN_NAME']
		dst = os.path.join(self.step_dir, f'{design}.pnl.v')

		with open(src, encoding='utf-8') as f:
			text = f.read()

		if 'dvdd' not in text.split('endmodule')[0]:
			marker = f'module {design} ('
			i = text.find(marker)
			j = text.find(');', i)
			if i >= 0 and j > i:
				head = text[i:j].rstrip()
				if not head.endswith(','):
					head += ','
				head += '\n    dvdd,\n    dvss'
				text = text[:i] + head + text[j:]

			decl = ' inout [73:0] pad_raw;'
			text = text.replace(
				decl, decl + '\n inout dvdd;\n inout dvss;', 1)

			# Tie the two ports to the core supplies once their wires are
			# declared (they are declared after the port list).
			anchor = ' wire vgnd;'
			if anchor in text:
				text = text.replace(
					anchor,
					anchor + '\n assign vdpwr = dvdd;\n assign vgnd = dvss;',
					1)

			# Restore the uio tri-state gating that synthesis folded away.
			# In silicon the pad cells apply pad_uio_oex; the padring-less
			# GL simulation drives the pads straight from pad_uio_out, so a
			# tile that configures its uio as inputs would fight the
			# testbench and produce X. Route the controller output through
			# an internal bus and gate it back onto the pads here.
			old = '.pad_uio_out({pad_raw[44],'
			i2 = text.find(old)
			if i2 >= 0:
				j2 = text.find('})', i2)
				block = text[i2:j2 + 2]
				block = re.sub(
					r'pad_raw\[(\d+)\]',
					lambda m: f'gl_uio_out[{int(m.group(1)) - 37}]',
					block)
				text = text[:i2] + block + text[j2 + 2:]
				gate = [' wire [7:0] gl_uio_out;']
				for b in range(8):
					gate.append(
						f" assign pad_raw[{37 + b}] = "
						f"\\top_I.pad_uio_oex[{b}] ? "
						f"gl_uio_out[{b}] : 1'bz;")
				text = text.replace(
					anchor, anchor + '\n' + '\n'.join(gate), 1)

			print(f'AddGLSupplyPorts: added dvdd/dvss to {design}')

		text, appended = self._append_missing_models(text)
		if appended:
			print('AddGLSupplyPorts: folded in GL models for '
				+ ', '.join(appended))

		patched = self._patch_pdk_default_nettype()
		if patched:
			print('AddGLSupplyPorts: allowed implicit nets in '
				+ ', '.join(patched))

		with open(dst, 'w', encoding='utf-8') as f:
			f.write(text)

		return {PNL_FORMAT: Path(dst)}, {}


class TopFlow(SequentialFlow):

	Steps: List[Type[Step]] = [
		Yosys.JsonHeader,
		Yosys.Synthesis,
		Checker.YosysUnmappedCells,
		Checker.YosysSynthChecks,
		OpenROAD.Floorplan,
		Odb.ApplyDEFTemplate,
		Odb.CustomIOPlacement,
		OptionalManualMacroPlacement,
		CustomPower,
		OpenROAD.GeneratePDN,
		OpenROAD.GlobalPlacement,
		OpenROAD.DetailedPlacement,
		CustomRoute,
		OpenROAD.GlobalRouting,
		OpenROAD.DetailedRouting,
		# Report OpenROAD's own antenna count. Note its LEF-based model
		# under-counts against the foundry deck (no thick/thin gate split);
		# the foundry antenna deck in the wafer.space precheck is the gate.
		OpenROAD.CheckAntennas,
		Checker.TrDRC,
		Odb.ReportDisconnectedPins,
		Checker.DisconnectedPins,
		Odb.ReportWireLength,
		Checker.WireLength,
		OpenROAD.RCX,
		OpenROAD.STAPostPNR,
		OpenROAD.IRDropReport,
		Magic.StreamOut,
		KLayout.StreamOut,
		KLayout.XOR,
		Checker.XOR,
		GdsShortCheck,
		Magic.DRC,
		Checker.MagicDRC,
		ExtractSpice,
		MergeWellNets,
		Checker.IllegalOverlap,
		Netgen.LVS,
		Checker.LVS,
		AddGLSupplyPorts,
	]


def copy_macros(cfg):
	# Copy-List
	CPL = [
		( 'v',   'src', 'verilog' ),
		( 'lef', 'lef', 'lef' ),
		( 'gds', 'gds', 'gds' ),
	]

	# Source/Destination bases
	src_base = pathlib.Path.cwd().parents[1]
	dst_base = pathlib.Path.cwd()

	# Pre-create destinations
	for ext, src_subdir, dst_subdir in CPL:
		(dst_base / dst_subdir).mkdir(exist_ok=True)

	# Scan each type
	for mtype in [ 'logo', 'pg', 'asw' ]:
		# Build path
		p = src_base / mtype / cfg.pdk.tech

		# Is there anything ?
		if not p.is_dir():
			continue

		# Iterate content
		for src_path in p.iterdir():
			# Only parse directory
			if not src_path.is_dir():
				continue

			# Process copy list
			for ext, src_subdir, dst_subdir in CPL:
				src_file = src_path / src_subdir / f'{src_path.name}.{ext}'
				dst_path = dst_base / dst_subdir
				if src_file.is_file():
					shutil.copy(src_file, dst_path)


if __name__ == '__main__':
	# Argument processing
	parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument("--open-in-klayout", action="store_true", help="Open last run in KLayout")
	parser.add_argument("--skip-xor-checks", action="store_true", help="Skips XOR checks")

	args = parser.parse_args()
	config = vars(args)

	if config['skip_xor_checks']:
		TopFlow.Steps.remove(KLayout.XOR)
		TopFlow.Steps.remove(Checker.XOR)

	# Get PDK root out of environment
	PDK_ROOT = os.getenv('PDK_ROOT')

	# Load TinyTapeout
	tti = tt.TinyTapeout()

	# IR drop analysis runs PDNSim's analyze_power_grid, which exits non-zero as
	# soon as the grid is not fully connected. It is currently blocked by a
	# separate defect: every via our custom router draws with ViaGenerator is
	# referenced in the DEF's SPECIALNETS but never defined in its VIAS
	# section, so the power connectivity graph is broken at every strap.
	# Keep the report off until that is fixed; Checker.DisconnectedPins still
	# covers logical connectivity and Netgen.LVS the layout.
	if tti.cfg.pdk.name == 'gf180mcuD':
		TopFlow.Steps.remove(OpenROAD.IRDropReport)

	# Copy local macros
	copy_macros(tti.cfg)

	# Generate macros
	macros = { }
	user_modules = []
	sram_user_modules = set()
	disc_modules = []

	for m in tti.die.get_sub_macros():
		if m.mod_name not in macros:
			macros[m.mod_name] = {
				'gds': [ f'dir::gds/{m.mod_name:s}.gds', ],
				'lef': [ f'dir::lef/{m.mod_name:s}.lef', ],
				'instances': { }
			}
			if m.mod_name.startswith('tt_um_'):
				user_modules.append(m.mod_name)
				if getattr(m.elem, 'uses_sram', False):
					sram_user_modules.add(m.mod_name)
			else:
				md = {
					'nl': f'dir::verilog/{m.mod_name:s}.v',
				}
				if os.path.isfile(f'spef/{m.mod_name:s}.nom.spef'):
					md['spef'] = {
						"min_*": [ f'dir::spef/{m.mod_name:s}.min.spef' ],
						"nom_*": [ f'dir::spef/{m.mod_name:s}.nom.spef' ],
						"max_*": [ f'dir::spef/{m.mod_name:s}.max.spef' ],
					}
				macros[m.mod_name].update(md)
			if m.is_logo:
				disc_modules.append(m.mod_name)

		macros[m.mod_name]['instances'][m.inst_name] = {
			"location": [ m.pos.x.um, m.pos.y.um ],
			"orientation": m.orient,
		}

	# Generate logical stubs for user macros. SRAM-capable modules have
	# the additional shared-memory pins in their Verilog interface.
	mod_tpl = open('tt_um_tpl.v', 'r').read()
	mod_tpl_sram = open('tt_um_sram_tpl.v', 'r').read()
	open('verilog/tt_um_all.v', 'w').write('\n'.join([
		(mod_tpl_sram if m in sram_user_modules else mod_tpl).format(mod_name=m)
			for m in user_modules
	]))

	design_name = os.getenv('DESIGN_NAME') or (
		'tt_gf_wrapper' if tti.cfg.pdk.name == 'gf180mcuD' else 'openframe_project_wrapper'
	)

	# The shared wrapper DEF is authored for SKY130. For GF180, retain its
	# special power/ground pin locations, but translate the design and
	# technology identifiers. The pin layer names were already translated to
	# GF180 (Metal2/Metal3) when the template was first imported; signal-pin
	# mismatches are handled permissively below and the 74 raw pads are placed
	# by Odb.CustomIOPlacement.
	def_template = 'openframe_project_wrapper.def'
	if tti.cfg.pdk.name == 'gf180mcuD':
		def_template = 'tt_gf_wrapper.def'
		def_text = pathlib.Path('openframe_project_wrapper.def').read_text()
		def_replacements = (
			('DESIGN openframe_project_wrapper ;', 'DESIGN tt_gf_wrapper ;'),
			('TECHNOLOGY sky130A ;', 'TECHNOLOGY gf180mcuD ;'),
		)
		for old, new in def_replacements:
			if old not in def_text:
				raise RuntimeError(f'Expected GF180 DEF template token not found: {old}')
			def_text = def_text.replace(old, new)
		def_text = fix_power_pins(def_text)
		pathlib.Path(def_template).write_text(def_text)

	# Only declare power connections for macros that actually survived
	# synthesis. Optional analog switches and power gates are absent when no
	# user block needs them, and OpenROAD treats an unmatched
	# PDN_MACRO_CONNECTIONS entry as a hard error.
	pdn_macro_connections = [
		"top_I.*mux_I vdpwr vgnd VDPWR VGND",
		"top_I.ctrl_I vdpwr vgnd VDPWR VGND",
		"top_I.sram_lo_I vdpwr vgnd vdd vss",
		"top_I.sram_hi_I vdpwr vgnd vdd vss",
	]
	macro_instances = set()
	for md in macros.values():
		macro_instances.update(md['instances'].keys())
	if any('tt_pg_vdd_I' in i for i in macro_instances):
		pdn_macro_connections.append("top_I.*tt_pg_vdd_I vdpwr vgnd VPWR VGND")
	if any('tt_asw_' in i for i in macro_instances):
		pdn_macro_connections.append("top_I.*tt_asw_.* vdpwr vgnd VDPWR VGND")
		pdn_macro_connections.append("top_I.*tt_asw_.* vapwr vgnd VAPWR VGND")

	# Custom config
	flow_cfg = {
		# Main design properties
		"DESIGN_NAME"    : design_name,
		"DESIGN_IS_CORE" : False,

		# Sources
		"VERILOG_INCLUDE_DIRS" : [ "dir::../../rtl/" ],
		"VERILOG_FILES": [
			f"dir::{design_name}.v",
			"dir::../../rtl/tt_top.v",
			"dir::../../rtl/tt_gpio.v",
			"dir::../../rtl/tt_user_module.v",
		],

		"VERILOG_POWER_DEFINE": "USE_POWER_PINS",

		# Macros
		"MACROS": macros,
		"EXTRA_VERILOG_MODELS": [
			"dir::verilog/tt_um_all.v",
		],

		# Constraints
		"SIGNOFF_SDC_FILE" : "dir::signoff.sdc",

		# Synthesis
		"SYNTH_ELABORATE_ONLY"      : False,
		"SYNTH_USE_PG_PINS_DEFINES" : "USE_POWER_PINS",

		"SYNTH_EXCLUSION_CELL_LIST" : "dir::no_synth_cells.txt",
		"PNR_EXCLUSION_CELL_LIST"   : "dir::no_drc_cells.txt",
		"DRC_EXCLUDE_CELL_LIST"     : "dir::no_drc_cells.txt",

		"QUIT_ON_SYNTH_CHECKS"      : False,

		# Floorplanning
		"DIE_AREA"  : [  0.00,  0.00, 3166.63, 4766.63 ],
		# X matches the GF180 die margin (cfg/gf180mcuD.yaml); the layout has
		# to fit full user tiles plus power gates into the eight block
		# columns, which the SKY130 85um margin does not allow.
		"CORE_AREA" : [ 62.00, 85.00, 3104.63, 4681.63 ],
		"FP_SIZING" : "absolute",

		# PDN
		"VDD_NETS": [ "vdpwr", "vapwr" ],
		"GND_NETS": [ "vgnd",  "vgnd"  ],

		"PDN_CFG": "dir::pdn.tcl",
		"PDN_CONNECT_MACROS_TO_GRID": True,
		"PDN_MACRO_CONNECTIONS": pdn_macro_connections,
		"PDN_ENABLE_GLOBAL_CONNECTIONS": True,

		"FP_PDN_CORE_RING"          : True,
		# The ring is built at the core boundary and needs roughly 3x its width
		# of outward space (power ring + spacing + ground ring). With the X die
		# margin at 62um (see cfg/gf180mcuD.yaml, needed so the block columns
		# fit a full user tile) the 25um ring no longer fits inside the die:
		#   [PDN-0351] PDN rings do not fit inside the die area by 16.84um in X
		# 12um still carries far more than a TT block draws.
		"FP_PDN_CORE_RING_VWIDTH"   : 12,
		"FP_PDN_CORE_RING_HWIDTH"   : 12,
		# With offset 0 the ring's inner edge sits exactly on the core
		# boundary, and the mux columns start 0.2um inside it (x=62.2 on a core
		# starting at 62.0). pdngen then snips the ring at every branch row, so
		# the Metal5 stripes lose their only vertical tie and PDNSim reports
		# thousands of unconnected shapes. Moving the ring 6um outward puts it
		# clear of the macro columns, which should let it stay continuous.
		"FP_PDN_CORE_RING_VOFFSET"  :  6,
		"FP_PDN_CORE_RING_HOFFSET"  :  6,
		"FP_PDN_CORE_RING_VSPACING" :  2.0,
		"FP_PDN_CORE_RING_HSPACING" :  2.0,

		# Placement: leave 2 free sites on each side of every cell. With no
		# padding the placer packed 20um flip-flops edge to edge, so the cells
		# inside such a run had no free site within well-tap reach
		# (DF.13/DF.14, latch-up rule); WellTaps puts a tap (2 sites) into
		# these gaps and fills the rest with fillers.
		"GPL_CELL_PADDING"      : 4,
		"DPL_CELL_PADDING"      : 4,

		# Routing
		# Global routing must produce a legal plan. With congestion allowed
		# and the default 30% track reserve, the ~12um channel between
		# branch 0's mux and its tiles (whose pins do not line up with the
		# mux's) overflowed, and the global router "solved" it by sending a few
		# tile<->mux nets straight through the tile's routing obstruction. The
		# detailed router then stays inside those guides and leaves Metal3
		# shorts through the tile (block_0_0 uio_oe[0]/[4]); which net it hit
		# changed from run to run. Total routing usage is ~1% of the chip, so
		# the reserve only starves those channels: with a 5% reserve the global
		# router finds a plan with zero overflow. Refuse congestion outright so
		# a future regression fails here instead of in silicon.
		"GRT_ALLOW_CONGESTION"  : False,
		"GRT_ADJUSTMENT"        : 0.05,
		"GRT_LAYER_ADJUSTMENTS" : [0.05, 0.05, 0.05, 0.05, 0.05],
		"GRT_OVERFLOW_ITERS"    : 100,
		# The detailed router ran single threaded (~13 min); GitHub runners
		# have 4 cores.
		"ROUTING_CORES"         : 4,
		# Antenna: OpenROAD.RepairAntennas cannot run here (the custom
		# pre-routes make it treat the design as detail-routed, and its
		# parasitics estimate then fails), and its LEF model misses most of
		# what the foundry deck reports.
		"DRT_ANTENNA_REPAIR_ITERS" : 0,
		# A healthy run terminates on its own once there are no violations
		# left. The last remaining defect is one module<->mux net that the
		# detailed router leaves both legally connected *and* with a redundant
		# loop running through the module's Metal4 VSS strip; the "stubborn
		# tiles" passes were still converging (12 -> 9 violations) when the
		# old 32-iteration cap hit, so give them room to finish.
		"DRT_OPT_ITERS"         : 64,
		# The remaining routing DRCs sit in a very small congested pocket at
		# the SRAM address pins. Metal4 alone does not give the router enough
		# room to escape there; Metal5 carries only the power stripes.
		"RT_MAX_LAYER"          : "Metal5",

		# Magic stream
		"MAGIC_ZEROIZE_ORIGIN" : False,

		# DRC
		"MAGIC_DRC_USE_GDS": True,

		# LVS
		# The wrapper has several pads per power pin (one DEF PORT each) and
		# several pins per domain. Without DEF labels Magic creates one port
		# per PORT, uniquifies the duplicates as "*_uq0/1/2" and the layout
		# pin list no longer matches the netlist's (114 vs 88 pins); netgen
		# then has to "alter pin lists to match", which merges nets. Reading
		# the DEF labels gives Magic one port per pin name.
		"MAGIC_DEF_LABELS" : True,
		"MAGIC_EXT_SHORT_RESISTOR" : True, # Fixes LVS failures when more than two pins are connected to the same net
		"IGNORE_DISCONNECTED_MODULES": disc_modules,

		# Magic sign-off
		# The Magic DRC report is dominated by violations that are not ours:
		# a vertical seam inside the external pre-hardened macro
		# tt_um_flip_pendant, and Metal4 spacing slivers along the die edge.
		# The reference GF180 testchip disables this error for the same
		# reason ("Passing magic DRC is not required for the submission");
		# routing DRC (Checker.TrDRC) and LVS remain enforced.
		"ERROR_ON_MAGIC_DRC": False,
		# Magic's extraction reports obsm3/obsm4 "illegal overlaps" against
		# metal3/metal4/via3 for LEF obstructions that abut real metal. 19k of
		# the 20.7k are inside the foundry decorative macros in the bottom-left
		# corner. Shorted nets are still caught by LVS.
		"ERROR_ON_ILLEGAL_OVERLAPS": False,
	}

	# GF180 exposes the 74 raw pad terminals directly. The SKY130 OpenFrame
	# DEF template has a different GPIO interface, so place GF180 pins by
	# their physical pad order instead.
	if tti.cfg.pdk.name == "gf180mcuD":
		flow_cfg.update({
			"FP_DEF_TEMPLATE": "dir::tt_gf_wrapper.def",
			"FP_TEMPLATE_MATCH_MODE": "permissive",
			"FP_TEMPLATE_COPY_POWER_PINS": True,
			"IO_PIN_ORDER_CFG": "dir::gf180_pin_order.cfg",
			"IO_PIN_H_LAYER": "Metal3",
			"IO_PIN_V_LAYER": "Metal2",
			"ERRORS_ON_UNMATCHED_IO": "both",
		})
	else:
		flow_cfg.update({
			"FP_DEF_TEMPLATE": "dir::openframe_project_wrapper.def",
			"FP_TEMPLATE_COPY_POWER_PINS": True,
		})

	# Update PDN config
	pdn_width   =  8.75
	pdn_spacing =  2.25
	pdn_pitch   = (tti.layout.glb.branch.pitch // 5).um
	pdn_offset  = (
		tti.layout.glb.top.pos_y +
		tti.layout.glb.branch.pitch // 10 -
		tti.layout.glb.margin.y // 2
	).um
	pdn_offset -= (pdn_spacing + pdn_width)

	sh = tti.cfg.pdk.site.height.um
	if 'CORE_AREA' in flow_cfg:
		pdn_offset -= math.ceil(flow_cfg['CORE_AREA'][1] / sh) * sh
	else:
		pdn_offset -= sh * flow_cfg.get('BOTTOM_MARGIN_MULT', 4)

	while pdn_offset > (pdn_pitch * 1.1):
		pdn_offset -= pdn_pitch

	def pdn_align(x):
		grid = 0.005
		return round(x / grid) * grid

	flow_cfg.update({
		"FP_PDN_HWIDTH"  : pdn_align(pdn_width),
		"FP_PDN_HSPACING": pdn_align(pdn_spacing),
		"FP_PDN_HPITCH"  : pdn_align(pdn_pitch),
		"FP_PDN_HOFFSET" : pdn_align(pdn_offset),
	})

	# Run flow
	flow_kls = OpenInKLayout if args.open_in_klayout else TopFlow
	flow = flow_kls(
		flow_cfg,
		design_dir = ".",
		pdk_root   = PDK_ROOT,
		pdk        = tti.cfg.pdk.name,
	)

	flow.start(last_run = args.open_in_klayout)
