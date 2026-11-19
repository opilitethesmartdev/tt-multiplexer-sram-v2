#!/usr/bin/env python3

#
# OpenLane2 build script to harden the tt_top macro inside
# the openframe_project_wrapper
#
# Copyright (c) 2023 Sylvain Munaut <tnt@246tNt.com>
# SPDX-License-Identifier: Apache-2.0
#

import argparse
import json
import math
import os
import pathlib
import shutil
import sys

from typing import List, Type

from librelane.flows.misc import OpenInKLayout
from librelane.flows.sequential import SequentialFlow
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
		Magic.DRC,
		Checker.MagicDRC,
		Magic.SpiceExtraction,
		Checker.IllegalOverlap,
		Netgen.LVS,
		Checker.LVS,
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
		pathlib.Path(def_template).write_text(def_text)

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
		"SYNTH_ELABORATE_ONLY"      : True,
		"SYNTH_USE_PG_PINS_DEFINES" : "USE_POWER_PINS",

		"SYNTH_EXCLUSION_CELL_LIST" : "dir::no_synth_cells.txt",
		"PNR_EXCLUSION_CELL_LIST"   : "dir::no_drc_cells.txt",
		"DRC_EXCLUDE_CELL_LIST"     : "dir::no_drc_cells.txt",

		"QUIT_ON_SYNTH_CHECKS"      : False,

		# Floorplanning
		"DIE_AREA"  : [  0.00,  0.00, 3166.63, 4766.63 ],
		"CORE_AREA" : [ 85.00, 85.00, 3081.63, 4681.63 ],
		"FP_SIZING" : "absolute",

		# PDN
		"VDD_NETS": [ "vdpwr", "vapwr" ],
		"GND_NETS": [ "vgnd",  "vgnd"  ],

		"PDN_CFG": "dir::pdn.tcl",
		"PDN_CONNECT_MACROS_TO_GRID": True,
		"PDN_MACRO_CONNECTIONS": [
			"top_I.*mux_I vdpwr vgnd VDPWR VGND",
			"top_I.ctrl_I vdpwr vgnd VDPWR VGND",
			"top_I.*tt_pg_vdd_I vdpwr vgnd VPWR VGND",
			"top_I.*tt_asw_.* vdpwr vgnd VDPWR VGND",
			"top_I.*tt_asw_.* vapwr vgnd VAPWR VGND",
			"top_I.sram_lo_I vdpwr vgnd VPWR VGND",
			"top_I.sram_hi_I vdpwr vgnd VPWR VGND",
		],
		"PDN_ENABLE_GLOBAL_CONNECTIONS": True,

		"FP_PDN_CORE_RING"          : True,
		"FP_PDN_CORE_RING_VWIDTH"   : 25,
		"FP_PDN_CORE_RING_HWIDTH"   : 25,
		"FP_PDN_CORE_RING_VOFFSET"  :  0,
		"FP_PDN_CORE_RING_HOFFSET"  :  0,
		"FP_PDN_CORE_RING_VSPACING" :  2.0,
		"FP_PDN_CORE_RING_HSPACING" :  2.0,

		# Routing
		"GRT_ALLOW_CONGESTION"  : True,
		"GRT_REPAIR_ANTENNAS"   : False,
		"DRT_ANTENNA_REPAIR_ITERS" : 0,
		"RT_MAX_LAYER"          : "Metal4",

		# Magic stream
		"MAGIC_ZEROIZE_ORIGIN" : False,

		# DRC
		"MAGIC_DRC_USE_GDS": True,

		# LVS
		"MAGIC_DEF_LABELS" : False,
		"MAGIC_EXT_SHORT_RESISTOR" : True, # Fixes LVS failures when more than two pins are connected to the same net
		"IGNORE_DISCONNECTED_MODULES": disc_modules,
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
