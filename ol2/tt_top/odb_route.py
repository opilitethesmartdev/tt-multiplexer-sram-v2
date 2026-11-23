#
# OpenDB script for custom IO routing for tt_top / user_project_wrapper
#
# Copyright (c) 2023 Sylvain Munaut <tnt@246tNt.com>
# SPDX-License-Identifier: Apache-2.0
#

import os
import sys
import yaml
from collections import namedtuple

import odb

sys.path.append('../../py')
import tt
import tt_odb

import click

from reader import click_odb


def getOtherITermsOnNet(it):
	return [x for x in it.getNet().getITerms() if x.this != it.this]


# Master name prefixes of the PDK standard cell libraries. These cells are
# fully described by their LEF and are handled by the placer/router directly.
STDCELL_PREFIXES = (
	'gf180mcu_fd_sc_',
	'sky130_fd_sc_',
	'sg13g2_',
)


class Router:

	def __init__(self, reader, tti):
		# Save vars
		self.reader = reader
		self.tti    = tti

		# Find useful data
		tech = reader.db.getTech()

		self.layer_h = tech.findLayer('Metal3')
		self.layer_v = tech.findLayer('Metal4')
		self.via     = ViaGenerator(reader, 'Via3_GEN_HH').get(1, 1)

		self.x_spine = []
		self.y_muxes = {}

	def _dbu(self, v):
		# Convert a nanometre value from the layout config to OpenDB
		# database units (GF180 uses 2000 dbu/µm, SKY130 1000).
		return int(v) * self.reader.block.getDbUnitsPerMicron() // 1000

	def route_vspine_net(self, net):
		# Find extents as well as Y mux pos and X spine pos
		x_min   = None
		x_max   = None

		y_min   = None
		y_max   = None

		x_spine = None
		y_mux   = dict()
		y_ctrl  = [None, None]

		for it in net.getITerms():
			# Get coordinates
			r, x, y = it.getAvgXY()
			if r is not True:
				continue

			# Collect the extent
			if (y_min is None) or (y < y_min):
				y_min = y

			if (y_max is None) or (y > y_max):
				y_max = y

			name = it.getInst().getName()
			if 'ctrl_I' in name:
				x_spine = x
				self.x_spine.append(x)
			else:
				y_mux.setdefault(y, []).append(x)
				self.y_muxes.setdefault(name, (x, []))[1].append(y)

		# Create wire and matching encoder
		wire = odb.dbWire.create(net)

		encoder = odb.dbWireEncoder()
		encoder.begin(wire)

		# Create vertical spine
		encoder.newPath(self.layer_v, 'FIXED')
		encoder.addPoint(x_spine, y_min)
		encoder.addPoint(x_spine, y_max)

		# Create horizontal link for each mux
		for y,xl in y_mux.items():
			xl.append(x_spine)
			x_min_l = min(xl)
			x_max_l = max(xl)

			encoder.newPath(self.layer_h, 'FIXED')
			if x_min_l < x_spine:
				encoder.addPoint(x_min_l, y)
			encoder.addPoint(x_spine, y)
			if x_max_l > x_spine:
				encoder.addPoint(x_max_l, y)

			encoder.newPath(self.layer_v, 'FIXED')
			encoder.addPoint(x_spine, y)
			encoder.addVia(self.via)

		encoder.end()

	def route_vspine(self):
		# Find controller
		ctrl_inst = self.reader.block.findInst('top_I.ctrl_I')

		# Route each spine net
		for i in range(self.tti.layout.vspine.iw):
			self.route_vspine_net(ctrl_inst.findITerm(f'spine_bot_iw[{i:d}]').getNet())
			self.route_vspine_net(ctrl_inst.findITerm(f'spine_top_iw[{i:d}]').getNet())

		for i in range(self.tti.layout.vspine.ow):
			self.route_vspine_net(ctrl_inst.findITerm(f'spine_bot_ow[{i:d}]').getNet())
			self.route_vspine_net(ctrl_inst.findITerm(f'spine_top_ow[{i:d}]').getNet())

	def create_spine_obs(self):
		# Find top/bottom
		y_min = min(sum([yl for xl,yl in self.y_muxes.values()], []))
		y_max = max(sum([yl for xl,yl in self.y_muxes.values()], []))

		# Create vspine obstruction
		x_min_spine = min(self.x_spine)
		x_max_spine = max(self.x_spine)

		odb.dbObstruction_create(self.reader.block,
			self.layer_v,
			x_min_spine, y_min,
			x_max_spine, y_max,
		)

		# Create horizontal link obstruction for each mux
		for k, v in self.y_muxes.items():
			x_min_hlink = min([v[0], x_min_spine])
			x_max_hlink = max([v[0], x_max_spine])
			y_min_hlink = min(v[1])
			y_max_hlink = max(v[1])

			odb.dbObstruction_create(self.reader.block,
				self.layer_h,
				x_min_hlink, y_min_hlink,
				x_max_hlink, y_max_hlink,
			)

	def create_macro_obs(self):
		# Get all layers
		tech = self.reader.db.getTech()

		layers = [
			tech.findLayer(ln)
				for ln in
					self.tti.cfg.pdk.tracks._cfg.keys()
		]

		mx = self._dbu(self.tti.layout.glb.margin.x)
		my = self._dbu(self.tti.layout.glb.margin.y)

		# Iterate over all hard macros
		for inst in self.reader.instances:
			master_name = inst.getMaster().getName()

			# The Arrakeen SRAM macros already declare Metal1-3 obstructions
			# in their LEF and expose all their signal/power pins on Metal3.
			# Blocking their whole footprint (in particular Metal4/Metal5)
			# leaves the detailed router no way to escape those pins, so it
			# ends up routing on Metal2/Metal3 inside the macro and shorting
			# against the macro obstructions.
			if master_name.startswith('SP6TSRAM'):
				continue

			# Standard cells describe their complete geometry in their LEF,
			# so they must stay routable. Blanketing them removes every
			# routing resource over the glue logic, which leaves the router
			# no legal path between those cells: it then routes into the
			# obstructions and reports thousands of Short violations
			# against them.
			if master_name.startswith(STDCELL_PREFIXES):
				continue

			bb = inst.getBBox()
			for l in layers:
				odb.dbObstruction_create(self.reader.block,
					l,
					bb.xMin() + mx,
					bb.yMin() + my,
					bb.xMax() - mx,
					bb.yMax() - my,
				)

	def route_pad(self):
		# Vias
		tech = self.reader.db.getTech()

		via_m23 = ViaGenerator(self.reader, 'Via2_GEN_HH')
		via_m34 = ViaGenerator(self.reader, 'Via3_GEN_HH')

		# Find controller instance
		ctrl_inst = self.reader.block.findInst('top_I.ctrl_I')

		# Load data file
		data = yaml.load(open('route_data.yaml'), yaml.FullLoader)['ports']

		# Iterate through data file
		for port_name, rpts in data.items():
			# Starting point
			it = ctrl_inst.findITerm(port_name)
			if it is None:
				continue
			sx, sy = it.getAvgXY()[1:]

			# Net
			net = it.getNet()
			if net is None:
				continue

			# Ending point. In GF180 the controller's output pads (and their
			# output enables) pass through a tristate buffer in tt_gf_wrapper,
			# so the controller ITerm's net has no direct pad BTerm. The
			# inout pad_raw nets are also un-writable by dbWire.create, so
			# both cases are left for the detail router.
			bt = net.get1stBTerm()
			if bt is None:
				continue
			ex, ey = bt.getFirstPinLocation()[1:]
			el = bt.getBPins()[0].getBoxes()[0].getTechLayer()

			# Wire
			wire = odb.dbWire.create(net)
			if wire is None:
				continue

			# Set via type for intermediate routing points
			rpts = [(v, via_m34) for v in rpts]

			# Append ending point to intermediate routing points
			if len(rpts) & 1:
				rpts.extend([(ex, via_m23), (ey, None)])
			else:
				rpts.extend([(ey, via_m34), (ex, None)])

			# Encoder start
			encoder = odb.dbWireEncoder()
			encoder.begin(wire)

			encoder.newPath(self.layer_v, 'FIXED')
			encoder.addPoint(sx, sy)

			# Scan through routing points
			px = sx
			py = sy
			xy = True

			for pt, vt in rpts:
				# Next point
				if xy:
					py = pt
				else:
					px = pt

				encoder.addPoint(px, py)

				# Toggle routing direction
				xy ^= True

			# Add via
			if vt is not None:
				encoder.addVia(vt.get(1, 1))

			# Encoder end
			encoder.end()

	def route_um_tieoffs(self):
		# Get track info
		# We route horizontally on met4, non-preferred direction ...
		track_cfg = self.tti.cfg.pdk.tracks.Metal4.y
		track_offset = self._dbu(track_cfg.offset)
		track_pitch  = self._dbu(track_cfg.pitch)
		track_width  = self._dbu(track_cfg.width)

		def track_align(v):
			return track_offset + ((v - track_offset) // track_pitch) * track_pitch

		# Scan all the muxes
		for inst in self.reader.instances:
			# Not a mux -> skip
			if inst.getMaster().getName() != 'tt_mux':
				continue

			# Instance bounding box
			inst_bbox = inst.getBBox()
			inst_y_mid = ( inst_bbox.yMin() + inst_bbox.yMax() ) // 2

			# Scan all um_k_zero[]
			for k0_it in inst.getITerms():
				# Not right port ?
				if not k0_it.getMTerm().getName().startswith('um_k_zero'):
					continue

				# Get net and check if there are anything to tie
				k0_net = k0_it.getNet()
				if k0_net.getITermCount() <= 1:
					continue

				# Get layer
				layer = k0_it.getMTerm().getMPins()[0].getGeometry()[0].getTechLayer()

				# Get strap Y position
				sy = k0_it.getAvgXY()[2]

				if sy > inst_y_mid:
					sy = track_align(inst_bbox.yMax() + track_width + track_pitch - 1)
				else:
					sy = track_align(inst_bbox.yMin() - track_width)

				# Start custom routing
				wire = odb.dbWire.create(k0_net)

				encoder = odb.dbWireEncoder()
				encoder.begin(wire)

				# Collect all ITerms positions
				it_pos = [ it.getAvgXY()[1:] for it in k0_net.getITerms() ]
				it_pos.sort()

				# Horizontal strap spanning all ITerms
				encoder.newPath(layer, 'FIXED')
				encoder.addPoint(min([px for px, py in it_pos]), sy)
				encoder.addPoint(max([px for px, py in it_pos]), sy)

				# Vertical segment from the strap down to each ITerm
				for px, py in it_pos:
					encoder.newPath(layer, 'FIXED')
					encoder.addPoint(px, sy)
					encoder.addPoint(px, py)

				# End routing
				encoder.end()

	def route_um_signals(self):
		# Scan all the user modules
		for um_inst in self.reader.instances:
			# Is this a user module ?
			if not um_inst.getName().endswith('.tt_um_I'):
				continue

			# Find matching mux
			ena_net = um_inst.findITerm('ena').getNet()
			for it in ena_net.getITerms():
				if it.getInst().getMaster().getName() == 'tt_mux':
					mux_inst = it.getInst()
					break
			else:
				# WTF couln't find mux ...
				continue

			# Get Y coordinates we need to connect to/from
			y_bot, y_top = sorted([
				um_inst.getBBox().yMin(),
				um_inst.getBBox().yMax(),
				mux_inst.getBBox().yMin(),
				mux_inst.getBBox().yMax(),
			])[1:3]

			# Scan every connection
			for um_it in um_inst.getITerms():
				# Get the net
				net = um_it.getNet()

				# We only care about signals going between user module and
				# the mux and nowhere else
				net_it_lst = net.getITerms()

				if len(net_it_lst) != 2:
					continue

				for it in net_it_lst:
					if it.getInst().getMaster().getName() == 'tt_mux':
						mux_it = it
						break
				else:
					continue

				# We get the x coordinate from the mux since it's the only
				# we can trust
				_, x, _ = mux_it.getAvgXY()

				# Get layer too
				layer = mux_it.getMTerm().getMPins()[0].getGeometry()[0].getTechLayer()

				# Route the wire
				wire = odb.dbWire.create(net)

				encoder = odb.dbWireEncoder()
				encoder.begin(wire)
				encoder.newPath(layer, 'FIXED')
				encoder.addPoint(x, y_top)
				encoder.addPoint(x, y_bot)
				encoder.end()


	def k01_get_track(self, side, idx):
		# Get full die area
		die = self.reader.block.getDieArea()

		# Prepare recording of used tracks if not done already
		if not hasattr(self, 'k01_tracks'):
			self.k01_tracks = {
				'left':  [],
				'right': [],
				'bot':   [],
				'top':   [],
			}

		# Track config
		cfg_tv = self.tti.cfg.pdk.tracks.Metal4.x
		cfg_th = self.tti.cfg.pdk.tracks.Metal3.y

		# Alignement function
		def a(cfg, v):
			return cfg.offset + ((v - cfg.offset) // cfg.pitch) * cfg.pitch

		# Return requested track
		if side == 'left':
			t = cfg_tv.offset + cfg_tv.pitch * idx

		elif side == 'right':
			t = a(cfg_tv, die.xMax() - cfg_tv.pitch * idx)

		elif side == 'bot':
			t = cfg_th.offset + cfg_th.pitch * idx

		elif side == 'top':
			t = a(cfg_th, die.yMax() - cfg_th.pitch * idx)

		else:
			# ?!!?
			t = None

		self.k01_tracks[side].append(t)
		return t;

	def route_k01_gpio(self):
		# Get full die area
		die = self.reader.block.getDieArea()

		# Vias
		tech = self.reader.db.getTech()

		via = {
			('Metal2', 'Metal3'): ViaGenerator(self.reader, 'Via2_GEN_HH'),
			('Metal3', 'Metal4'): ViaGenerator(self.reader, 'Via3_GEN_HH'),
		}

		# Scan all BTerm to find gpio_loopback_{zero,one}[]
		for bterm in self.reader.block.getBTerms():
			# Check it's a bterm of interest
			if not bterm.getName().startswith('gpio_loopback'):
				continue

			# Select index
			if 'zero' in bterm.getName():
				idx = 0
			elif 'one' in bterm.getName():
				idx = 1

			# Select side
			bt_bbox = bterm.getBBox()
			if   bt_bbox.xMin() < die.xMin():
				side = 'left'
			elif bt_bbox.xMax() > die.xMax():
				side = 'right'
			elif bt_bbox.yMin() < die.yMin():
				side = 'bot'
			elif bt_bbox.yMax() > die.yMax():
				side = 'top'

			# Get track
			trk = self.k01_get_track(side, idx)

			# Get layer of bterm
			bterm_box = bterm.getBPins()[0].getBoxes()[0]
			bterm_ly  = bterm_box.getTechLayer()

			# Get the coordinates for all other bterms on net
			net = bterm.getNet()

			pos = []

			for bterm_sec in net.getBTerms():
				# Check it's in the same layer
				if bterm_sec.getBPins()[0].getBoxes()[0].getTechLayer().getName() != bterm_ly.getName():
					continue

				# Get position
				pr, px, py = bterm_sec.getFirstPinLocation()
				if pr is not True:
					continue

				# Record it
				pos.append( (px, py) )

			# Create new wire
			wire = odb.dbWire.create(net)

			# Encoder start
			encoder = odb.dbWireEncoder()
			encoder.begin(wire)

			# Draw
			if side in ['left', 'right']:
				# Vertical segment
				encoder.newPath(self.layer_v, 'FIXED')
				encoder.addPoint(trk, min([p[1] for p in pos]))
				encoder.addPoint(trk, max([p[1] for p in pos]))

				# Connect each position
				for px, py in pos:
					encoder.newPath(bterm_ly, 'FIXED')
					encoder.addPoint(px, py)
					encoder.addPoint(trk, py)
					encoder.addVia(via[(bterm_ly.getName(), self.layer_v.getName())].get(1, 1))

			elif side in ['bot', 'top']:
				# Horizontal segment
				encoder.newPath(self.layer_h, 'FIXED')
				encoder.addPoint(min([p[0] for p in pos]), trk)
				encoder.addPoint(max([p[0] for p in pos]), trk)

				# Connect each position
				for px, py in pos:
					encoder.newPath(bterm_ly, 'FIXED')
					encoder.addPoint(px, py)
					encoder.addPoint(px, trk)
					encoder.addVia(via[(bterm_ly.getName(), self.layer_h.getName())].get(1, 1))

			# Encoder end
			encoder.end()

	def route_k01_global(self):
		# Vias
		tech = self.reader.db.getTech()

		via = {
			('Metal2', 'Metal3'): ViaGenerator(self.reader, 'Via2_GEN_HH'),
			('Metal3', 'Metal4'): ViaGenerator(self.reader, 'Via3_GEN_HH'),
		}

		# Get full die area
		die = self.reader.block.getDieArea()

		# Find controller instance
		ctrl_inst = self.reader.block.findInst('top_I.ctrl_I')

		# Start index
		idx = 2

		# Deal with each constant
		for port_name in ['k_zero', 'k_one']:
			# ITerm on controller
			ctrl_iterm = ctrl_inst.findITerm(port_name)
			r, x, y = ctrl_iterm.getAvgXY()
			if r is not True:
				continue

			# Get associated net
			net = ctrl_iterm.getNet()

			# Check if there are any users
			if (net is None) or (len(net.getBTerms()) == 0):
				continue

			# Limits
			lx = [
				self.k01_get_track('left', idx),
				self.k01_get_track('right', idx),
			]

			ly = [
				self.k01_get_track('bot', idx),
				self.k01_get_track('top', idx),
			]

			idx += 1

			# Create new wire
			wire = odb.dbWire.create(net)

			# Encoder start
			encoder = odb.dbWireEncoder()
			encoder.begin(wire)

			# Line toward bottom
			encoder.newPath(self.layer_v, 'FIXED')
			encoder.addPoint(x, y)
			encoder.addPoint(x, ly[0])
			encoder.addVia(self.via)
			encoder.addPoint(lx[1], ly[0])
			encoder.addVia(self.via)
			encoder.addPoint(lx[1], ly[1])
			encoder.addVia(self.via)
			encoder.addPoint(lx[0], ly[1])
			encoder.addVia(self.via)
			encoder.addPoint(lx[0], ly[0])
			encoder.addVia(self.via)
			encoder.addPoint(x, ly[0])

			# Iterate over all BTerms
			for pad_bterm in net.getBTerms():
				# Get pin location / Bounding Box
				pr, px, py = pad_bterm.getFirstPinLocation()
				if pr is not True:
					continue

				pad_bb  = pad_bterm.getBBox()
				pad_box = pad_bterm.getBPins()[0].getBoxes()[0]
				pad_ly  = pad_box.getTechLayer()

				# Start path
				encoder.newPath(pad_ly, 'FIXED')
				encoder.addPoint(px, py)

				# Check side
				if pad_bb.yMin() < 0:				# Bottom
					encoder.addPoint(px, ly[0])
					encoder.addVia(via[(pad_ly.getName(), self.layer_h.getName())].get(1, 1))

				elif pad_bb.yMax() > die.yMax():	# Top
					encoder.addPoint(px, ly[1])
					encoder.addVia(via[(pad_ly.getName(), self.layer_h.getName())].get(1, 1))

				elif pad_bb.xMin() < 0:				# Left
					encoder.addPoint(lx[0], py)
					encoder.addVia(via[(pad_ly.getName(), self.layer_v.getName())].get(1, 1))

				elif pad_bb.xMax() > die.xMax():	# Right
					encoder.addPoint(lx[1], py)
					encoder.addVia(via[(pad_ly.getName(), self.layer_v.getName())].get(1, 1))

				else:
					# ?!?!?
					continue

			# Encoder end
			encoder.end()

	def create_k01_obs(self):

		# No tracks ?
		if not hasattr(self, 'k01_tracks'):
			return

		# Get all layers and config
		tech = self.reader.db.getTech()

		layer_v = tech.findLayer('Metal4')
		layer_h = tech.findLayer('Metal3')

		cfg_v = self.tti.cfg.pdk.tracks.Metal4.x
		cfg_h = self.tti.cfg.pdk.tracks.Metal3.y

		die = self.reader.block.getDieArea()

		# Limits
		if self.k01_tracks['left']:
			lx_left = [
				min(self.k01_tracks['left']) - cfg_v.pitch // 2,
				max(self.k01_tracks['left']) + cfg_v.pitch // 2,
			]
		else:
			lx_left = [ die.xMin(), die.xMin() ]

		if self.k01_tracks['right']:
			lx_right = [
				min(self.k01_tracks['right']) - cfg_v.pitch // 2,
				max(self.k01_tracks['right']) + cfg_v.pitch // 2,
			]
		else:
			lx_right = [ die.xMax(), die.xMax() ]

		if self.k01_tracks['bot']:
			ly_bot = [
				min(self.k01_tracks['bot']) - cfg_h.pitch // 2,
				max(self.k01_tracks['bot']) + cfg_h.pitch // 2,
			]
		else:
			ly_bot = [ die.yMin(), die.yMin() ]

		if self.k01_tracks['top']:
			ly_top = [
				min(self.k01_tracks['top']) - cfg_h.pitch // 2,
				max(self.k01_tracks['top']) + cfg_h.pitch // 2,
			]
		else:
			ly_top = [ die.yMax(), die.yMax() ]

		# Left
		if self.k01_tracks['left']:
			odb.dbObstruction_create(self.reader.block,
				layer_v, lx_left[0], ly_bot[0], lx_left[1], ly_top[1])

		# Right
		if self.k01_tracks['right']:
			odb.dbObstruction_create(self.reader.block,
				layer_v, lx_right[0], ly_bot[0], lx_right[1], ly_top[1])

		# Bottom
		if self.k01_tracks['bot']:
			odb.dbObstruction_create(self.reader.block,
				layer_h, lx_left[0], ly_bot[0], lx_right[1], ly_bot[1])

		# Top
		if self.k01_tracks['top']:
			odb.dbObstruction_create(self.reader.block,
				layer_h, lx_left[0], ly_top[0], lx_right[1], ly_top[1])



class ViaGenerator:

	def __init__(self, reader, via_rule_name):
		# No known via
		self.vias = {}

		# Save interesting vars
		self.reader = reader
		self.tech = tech = reader.db.getTech()

		# Find Via Rule
		self.via_rule = tech.findViaGenerateRule(via_rule_name)

		# Identify rules for top/cut/bot
		met = []

		for i in range(self.via_rule.getViaLayerRuleCount()):
			ly_rule = self.via_rule.getViaLayerRule(i)
			ly = ly_rule.getLayer()

			# Is it the cut ?
			if ly.getType() == 'CUT':
				self.cut_ly  = ly
				self.cut_sz  = [ ly_rule.getRect().dx(), ly_rule.getRect().dy() ]
				self.cut_spc = ly_rule.getSpacing()

				# The cut spacing in the rule is center to center
				# but when creating the via we need it border to border ?!?!
				self.cut_spc[0] -= self.cut_sz[0]
				self.cut_spc[1] -= self.cut_sz[1]

			# Or Metal ?
			elif ly.getType() == 'ROUTING':
				enc = ly_rule.getEnclosure()
				met.append( (ly.getName(), ly, enc) )

			# WTF ?
			else:
				raise RuntimeError('Unknown via rule')

		met = sorted(met)

		self.bot_ly  = met[0][1]
		self.bot_enc = met[0][2]

		self.top_ly  = met[1][1]
		self.top_enc = met[1][2]

	def create(self, ncols, nrows, name=None):
		# Create via
		if name is None:
			name = f'vg_{(hash(self) & 0xffffffff):08x}_{ncols:d}x{nrows:d}'

		v = odb.dbVia.create(self.reader.block, name)

		# Use a generate-rule via with explicit parameters. It is written to the
		# DEF's VIAS section as "+ VIARULE ... + CUTSIZE ... + ROWCOL ...", and
		# both Magic and KLayout resolve it without ambiguity.
		v.setViaGenerateRule(self.via_rule)

		# Configure params
		vp = v.getViaParams()

		vp.setBottomLayer(self.bot_ly)
		vp.setCutLayer(self.cut_ly)
		vp.setTopLayer(self.top_ly)
		vp.setNumCutCols(ncols)
		vp.setNumCutRows(nrows)
		vp.setXCutSize(self.cut_sz[0])
		vp.setYCutSize(self.cut_sz[1])
		vp.setXCutSpacing(self.cut_spc[0])
		vp.setYCutSpacing(self.cut_spc[1])
		vp.setXBottomEnclosure(self.bot_enc[0])
		vp.setYBottomEnclosure(self.bot_enc[1])
		vp.setXTopEnclosure(self.top_enc[0])
		vp.setYTopEnclosure(self.top_enc[1])

		v.setViaParams(vp)

		# Done
		return v

	def get(self, ncols, nrows):
		k = (ncols, nrows)
		if k not in self.vias:
			self.vias[k] = self.create(ncols, nrows)
		return self.vias[k]

	def get4sz(self, vw, vh):
		# Compute row / columns
		ncols = (vw // (self.cut_sz[0] + self.cut_spc[0])) - 1
		nrows = (vh // (self.cut_sz[1] + self.cut_spc[1])) - 1
		return self.get(ncols, nrows)

	def get4sz_ext(self, vw, vh, bot_fit='xy', top_fit='xy'):
		# Constraints
		ncols = []
		nrows = []

		if 'x' in bot_fit:
			ncols.append( (vw - 2 * self.bot_enc[0] + self.cut_spc[0]) // (self.cut_sz[0] + self.cut_spc[0]) )

		if 'x' in top_fit:
			ncols.append( (vw - 2 * self.top_enc[0] + self.cut_spc[0]) // (self.cut_sz[0] + self.cut_spc[0]) )

		if 'y' in bot_fit:
			nrows.append( (vh - 2 * self.bot_enc[1] + self.cut_spc[1]) // (self.cut_sz[1] + self.cut_spc[1]) )

		if 'y' in top_fit:
			nrows.append( (vh - 2 * self.top_enc[1] + self.cut_spc[1]) // (self.cut_sz[1] + self.cut_spc[1]) )

		ncols = min(ncols)
		nrows = min(nrows)

		# Safety check
		if (ncols <= 0) or (nrows <= 0):
			return None

		# Get final via
		return self.get(ncols, nrows)



class ModulePowerPadData(namedtuple('ModulePowerPadData', 'xc xw yb yt')):

	__slots__ = []

	@classmethod
	def from_geometry(kls, g, grid=1):
		xc = ((g.xMin() + g.xMax()) // (2 * grid)) * grid
		xw = min(g.xMax() - xc, xc - g.xMin()) * 2
		return kls(xc, xw, g.yMin(), g.yMax())


class ModulePowerStrapper:

	def __init__(self, reader, tti):
		# Save vars
		self.reader = reader
		self.tti    = tti

		# Find useful data
		tech = reader.db.getTech()

		self.vg = ViaGenerator(self.reader, 'Via4_GEN_HH')
		self.layer = tech.findLayer('Metal5')

		self.stripe_space, self.stripe_width = self._find_stripe_space_width()
		self.space = 2250 * reader.block.getDbUnitsPerMicron() // 1000
		self.grid = tech.getManufacturingGrid()

	def _grid_align(self, v):
		return (v // self.grid) * self.grid

	def _find_stripe_space_width(self):
		# Get all `met5` stripes for VGND
		net = self.reader.block.findNet('vgnd')
		sw = net.getSWires()[0]
		stripes = [
			w for w in sw.getWires() if (
				not w.isVia() and
				w.getTechLayer().getName() == 'Metal5' and
				w.getWireShapeType() == 'STRIPE'
			)
		]

		# Get spacing and width
		yl = sorted([x.yMin() for x in stripes])

		return (yl[1] - yl[0]), stripes[0].getDY()

	def _get_y_pos_width(self, pg_inst, pg_idx, pg_cnt):
		# Is it single or double height ?
		h = int(pg_inst.getMaster().getName()[-1])

		# Get switch physical dimensions
		bbox = pg_inst.getBBox()

		y_min = bbox.yMin()
		y_max = bbox.yMax()
		y_mid = (y_min + y_max) // 2

		# If we only have one power gate, allocate all to it
		if pg_cnt == 1:
			# Wide strip
			w = 2 * self.stripe_width + self.space

			# Select depending on height
			if h == 1:
				return [ ( y_mid, w ) ]

			elif h == 2:
				return [
					( y_mid + self.stripe_space, w ),
					( y_mid,                     w ),
					( y_mid - self.stripe_space, w ),
				]

			elif h == 4:
				spc = self.stripe_space // 2
				return [
					( y_mid + spc * 7, w ),
					( y_mid + spc * 5, w ),
					( y_mid + spc * 3, w ),
					( y_mid + spc * 1, w ),
					( y_mid - spc * 1, w ),
					( y_mid - spc * 3, w ),
					( y_mid - spc * 5, w ),
					( y_mid - spc * 7, w ),
				]

			else:
				raise RuntimeError('Unsupported heigh Power Gate')

		# If we have two, then the center one is split
		elif pg_cnt == 2:
			# Wide and narrow stripes + offset
			ww = 2 * self.stripe_width + self.space
			wn = self.stripe_width

			ofs1 = (1 - 2*pg_idx) * ((self.stripe_width + self.space) // 2)
			ofs2 = (2*pg_idx - 1) * self.stripe_space

			# Select depending on height
			if h == 1:
				return [ ( y_mid + ofs1, wn ) ]

			elif h == 2:
				return [
					( y_mid + ofs1, wn ),
					( y_mid + ofs2, ww ),
				]

			else:
				raise RuntimeError('Unsupported heigh Power Gate')

		# Huh ?
		else:
			raise RuntimeError('Unsupported number of Power Gates')


	def _get_pad_data(self, um_it, pg_it):
		# Find geometry for those terminals
		geom_um = [ x[1] for x in pg_it.getGeometries() ]
		geom_pg = [ x[1] for x in um_it.getGeometries() ]
		geom = geom_um + geom_pg

		# Extent ( + extra for worse case enclosure requirement )
		xl = min([x.xMin() for x in geom]) - self.vg.top_enc[0]
		xr = max([x.xMax() for x in geom]) + self.vg.top_enc[0]

		# Center positions and width
		pd = [ModulePowerPadData.from_geometry(g, grid=self.grid) for g in geom]

		# Attempt to merge contiguous pads
		pd.sort(key=lambda x: (x.xc, x.yb))

		pd_merged = []
		pad_cur = pd[0]

		for pad_nxt in pd[1:]:
			if pad_cur.xc == pad_nxt.xc and pad_cur.xw == pad_nxt.xw and pad_cur.yt >= pad_nxt.yb:
				# Merge
				pad_cur = ModulePowerPadData(pad_cur.xc, pad_cur.xw, pad_cur.yb, max(pad_cur.yt, pad_nxt.yt))
			else:
				# Discontinuous
				pd_merged.append(pad_cur)
				pad_cur = pad_nxt

		pd_merged.append(pad_cur)

		# Return result
		return xl, xr, pd_merged

	def _draw_stripe(self, sw, yp, yw, xl, xr, pd):
		# Stripe
		odb.createSBoxes(sw, self.layer, [odb.Rect(xl, yp-yw//2, xr, yp+yw//2)], "STRIPE")

		# Vias
		for pad in pd:
			# Default via param
			vx = pad.xc
			vy = yp
			vw = pad.xw
			vh = yw
			bot_fit = 'x'

			# Validate extent of pad (with ample argin for enclosure)
			if ((yp - yw * 0.55) < pad.yb) or ((yp + yw * 0.55) > pad.yt):
				# Doesn't fully fit, so be more restrictive
				bot_fit = 'xy'

				y_bot = max(pad.yb, yp - yw // 2)
				y_top = min(pad.yt, yp + yw // 2)

				vy = self._grid_align((y_top + y_bot) // 2)
				vh = min(y_top - vy, vy - y_bot) * 2

			# Get matching via
			via = self.vg.get4sz_ext(vw, vh, top_fit='y', bot_fit=bot_fit)
			if via is None:
				continue

			# Add it
			odb.createSBoxes(sw, via, [odb.Point(vx, vy)], "STRIPE")

	def run(self):

		# Find all user modules
		for um_inst in self.reader.block.getInsts():
			# Is it a user module ?
			if not um_inst.getName().endswith('.tt_um_I'):
				continue

			# Find power ITerms with power gate
			pg_list = []

			for um_it in um_inst.getITerms():
				# Power ?
				if not um_it.getSigType() == 'POWER':
					continue

				# Check if it's on a power gate
				if um_it.getNet().getITermCount() != 2:
					continue

				pg_it = getOtherITermsOnNet(um_it)[0]

				# Record
				pg_list.append( (um_it, pg_it) )

			# Connect each
			pg_cnt = len(pg_list)

			for pg_idx, (um_it, pg_it) in enumerate(pg_list):
				# Power gate instance
				pg_inst = pg_it.getInst()

				# Pick appropriate Y positions for straps
				ypw = self._get_y_pos_width(pg_inst, pg_idx, pg_cnt)

				# Get the X data (extent + via pos)
				xl, xr, pd = self._get_pad_data(um_it, pg_it)

				# Find net and create the matching special wire
				net = um_it.getNet()
				sw = odb.dbSWire.create(net, "ROUTED")

				# Draw for each y position
				for yp, yw in ypw:
					self._draw_stripe(sw, yp, yw, xl, xr, pd)


class MacroPowerVias:
	"""Tie the hardened macros' power pins into the Metal5 grid.

	Every macro in this design exposes its power pins on Metal4 (tt_mux,
	tt_ctrl, the power gates, the user modules, chip_rom) or on Metal3 (the
	Arrakeen SRAM). The Metal5 stripes are horizontal and cross both.

	pdngen's macro grid used to do this, but it drops a generate-rule via array
	sized from the pin, and these pins are up to 17um wide: the result was
	17.7 x 3.1um Via4 arrays on Metal4, which are special/fixed geometry the
	router cannot see - it then routed the module signal nets straight through
	them (11 Metal4.Short violations). The grid is gone from pdn.tcl and this
	step does the job with small, unambiguous single-cut vias instead.

	Connection, per net:
	  * Metal4 pin: one Via4 where the pin overlaps a same-net Metal5 stripe.
	  * Metal3 pin: Via3 up to Metal4, a short Metal4 jog to a same-net
	    Metal5 stripe, and a Via4 there. The jog crosses other pins of the
	    macro on Metal3, but without a via that is not a connection, and it
	    is the same net's own stripe it lands on.
	"""

	NETS = ('vdpwr', 'vgnd', 'vapwr')

	def __init__(self, reader):
		self.reader = reader
		self.tech = reader.db.getTech()
		self.dbu = reader.block.getDbUnitsPerMicron()

		self.v34 = ViaGenerator(reader, 'Via3_GEN_HH')
		self.v45 = ViaGenerator(reader, 'Via4_GEN_HH')
		self.m4 = self.tech.findLayer('Metal4')

		# Via footprints, used as the minimum pin/stripe overlap.
		self.min_m4 = (self.v45.cut_sz[0] + 2 * self.v45.bot_enc[0],
			self.v45.cut_sz[1] + 2 * self.v45.bot_enc[1])
		self.min_m3 = (self.v34.cut_sz[0] + 2 * self.v34.bot_enc[0],
			self.v34.cut_sz[1] + 2 * self.v34.bot_enc[1])

		self.stripes = {}
		for name in self.NETS:
			net = reader.block.findNet(name)
			rects = []
			if net is not None:
				for sw in net.getSWires():
					for w in sw.getWires():
						if w.isVia():
							continue
						if w.getTechLayer().getName() != 'Metal5':
							continue
						rects.append((w.xMin(), w.yMin(), w.xMax(), w.yMax()))
			self.stripes[name] = rects

		self.seen = set()
		self.reasons = {'no_stripe': 0, 'too_small': 0, 'claimed': 0,
			'jogged': 0}

		# Vias already on these nets: pdngen's macro arrays and ring/stripe
		# vias, ModulePowerStrapper's gated-domain straps, StdCellPower's
		# risers. Where one already sits, do not add ours on top - overlapping
		# cuts are merged differently by Magic (5nm GDS grid) and KLayout
		# (1nm), which is a 1nm XOR sliver for every cut.
		self.existing = {}
		for _name in self.NETS:
			_net = reader.block.findNet(_name)
			_boxes = []
			if _net is not None:
				for _sw in _net.getSWires():
					for _w in _sw.getWires():
						if not _w.isVia():
							continue
						_boxes.append((_w.xMin() - 400, _w.yMin() - 400,
							_w.xMax() + 400, _w.yMax() + 400))
			self.existing[_name] = _boxes

	def _claim_via(self, net_name, x, y):
		for x0, y0, x1, y1 in self.existing.get(net_name, ()):
			if (x0 <= x + 400) and (x1 >= x - 400) and \
					(y0 <= y + 400) and (y1 >= y - 400):
				return False
		# A macro's power pins are hundreds of microns apart, so an exact
		# coordinate is a fine identity for our own placements.
		key = (net_name, x, y)
		if key in self.seen:
			return False
		self.seen.add(key)
		return True

	def _nearest_stripe(self, name, y):
		best = None
		for st in self.stripes[name]:
			d = 0 if (st[1] <= y <= st[3]) else min(abs(y - st[1]), abs(y - st[3]))
			if best is None or d < best[0]:
				best = (d, st)
		return best[1] if best is not None else None

	def _m4_pin(self, net, r):
		best = None
		for st in self.stripes[net.getName()]:
			ox = min(r.xMax(), st[2]) - max(r.xMin(), st[0])
			oy = min(r.yMax(), st[3]) - max(r.yMin(), st[1])
			if ox <= 0 or oy <= 0:
				continue
			area = ox * oy
			if best is None or area > best[0]:
				best = (area, ox, oy, st)
		if best is None:
			self.reasons['no_stripe'] += 1
			return 0
		_, ox, oy, st = best
		if getattr(self, '_short', 0) < 8:
			self._short = getattr(self, '_short', 0) + 1
			w = (r.xMax() - r.xMin()) / self.dbu
			h = (r.yMax() - r.yMin()) / self.dbu
			print(f'MacroPowerVias._m4_pin master={self._cur_master} '
				f'net={net.getName()} pin {w:.2f}x{h:.2f}um '
				f'overlap ox={ox/self.dbu:.2f} oy={oy/self.dbu:.2f} '
				f'min_m4={self.min_m4[0]/self.dbu:.2f}x{self.min_m4[1]/self.dbu:.2f}')
		if ox < self.min_m4[0] or oy < self.min_m4[1]:
			self.reasons['too_small'] += 1
			return 0
		# The via must sit on the manufacturing grid: Magic streams GDS on a
		# 5nm grid while KLayout keeps 1nm, so a half-grid centre puts every
		# cut edge on a 2.5nm coordinate and the two streams disagree by 1nm
		# all around the cut (hundreds of XOR slivers).
		x = self._snap((max(r.xMin(), st[0]) + min(r.xMax(), st[2])) // 2)
		y = self._snap((max(r.yMin(), st[1]) + min(r.yMax(), st[3])) // 2)
		# Discrete 1x1 vias, spaced along the overlap. A multi-cut generate
		# array is packed from the pin's own size and its neighbouring cuts
		# end up touching, which Magic (which merges cuts when streaming GDS)
		# and KLayout (which keeps them apart) resolve differently - that is
		# what produced 1046 Via4 XOR slivers. 1x1 vias are unambiguous.
		step = 1200
		n = max(1, min(4, ox // step))
		lo_x = max(r.xMin(), st[0]) + self.min_m4[0] // 2
		hi_x = min(r.xMax(), st[2]) - self.min_m4[0] // 2
		sw = None
		placed_here = 0
		for k in range(n):
			xk = self._snap(lo_x + (hi_x - lo_x) * k // max(1, n - 1) if n > 1 else x)
			if not self._claim_via(net.getName(), xk, y):
				self.reasons['claimed'] += 1
				continue
			if sw is None:
				sw = odb.dbSWire.create(net, "ROUTED")
			odb.createSBoxes(sw, self.v45.get(1, 1), [odb.Point(xk, y)], "STRIPE")
			placed_here += 1
		if placed_here:
			return 1

		return 0

	def _m3_pin(self, net, r, idx):
		# A Metal3 power pin (the Arrakeen SRAM's interleaved vdd/vss strips):
		# Via3 up to Metal4, a short Metal4 jog to the nearest same-net Metal5
		# stripe, and a Via4 there. The jog crosses other strips of the macro
		# on Metal3, but without a via that is not a connection, and the same
		# net's own stripe is where it lands.
		st = self._nearest_stripe(net.getName(), (r.yMin() + r.yMax()) // 2)
		if st is None:
			return 0

		# Jog near the pin's end: the SRAM's signal pins are on the left
		# edge, so the far end is clear.
		x = self._snap(r.xMax() - (idx + 1) * 1200)
		if x < r.xMin() + 400 or x > r.xMax() - 400:
			x = (r.xMin() + r.xMax()) // 2

		y0 = self._snap((r.yMin() + r.yMax()) // 2)
		y1 = self._snap((st[1] + st[3]) // 2)

		if not self._claim_via(net.getName(), x, y1):
			self.reasons['claimed'] += 1
			return 0

		# 0.8um wide, so the Via4 enclosure (0.76um) sits inside it.
		sw = odb.dbSWire.create(net, "ROUTED")
		odb.createSBoxes(sw, self.m4, [
			odb.Rect(x - 400, min(y0, y1), x + 400, max(y0, y1)),
		], "STRIPE")
		odb.createSBoxes(sw, self.v34.get(1, 1), [odb.Point(x, y0)], "STRIPE")
		odb.createSBoxes(sw, self.v45.get(1, 1), [odb.Point(x, y1)], "STRIPE")
		return 1

	def _snap(self, v):
		return (v // self.grid) * self.grid

	def run(self):
		self.grid = self.reader.db.getTech().getManufacturingGrid()

		n4 = 0
		n3 = 0
		# One Metal3 connection per (instance, net) is enough: a macro's power
		# strips are the same net inside the macro. Each one needs a long
		# Metal4 jog to reach a stripe, and that jog is special geometry the
		# router cannot see - 27 of them cost 3500 net mismatches when the
		# router happened to route across them.
		done_m3 = set()
		self._short = 0
		self._cur_master = None
		for inst in self.reader.block.getInsts():
			master = inst.getMaster().getName()
			self._cur_master = master
			if master.startswith(STDCELL_PREFIXES):
				continue
			idx = 0
			for it in inst.getITerms():
				net = it.getNet()
				if net is None or net.getName() not in self.NETS:
					continue
				for geom in it.getGeometries():
					layer, r = geom[0], geom[1]
					if not hasattr(layer, 'getName'):
						continue
					ly = layer.getName()
					if ly == 'Metal4':
						n4 += self._m4_pin(net, r)
						# NOTE: do not obstruct the pin here. On the user
						# modules the power pins sit on the same edge as the
						# signal pins, so a pin-shaped obstruction also covers
						# the signal pin next to it (uio_oe[0]) and leaves the
						# net with no legal escape at all - the router then
						# reports obstruction violations instead of shorts.
					elif ly == 'Metal3':
						key = (inst.getName(), net.getName())
						if key not in done_m3:
							if self._m3_pin(net, r, idx):
								done_m3.add(key)
								n3 += 1
						idx += 1

		print(f'MacroPowerVias: {n4} Metal4 pins and {n3} Metal3 pins tied '
			f'to the stripes, reasons={self.reasons}')


class WellTaps:
	"""Insert well-tap cells next to the placed standard cells.

	The standard cells expose well pins (VNW/VPW), but the extractor can only
	see geometry: without a tap, the n-well of each logic cluster is a floating
	net (LVS: `_NNN_/VNW`) and the wells would float in silicon.

	The stock tapcell step fills every free row of the core with fillties -
	67,846 cells here, because most of the core is macro-free empty row - and
	then trips an OpenROAD DPL padding-check bug on the off-row decorative
	macros (DPL-0011 for a fixed block whose bottom is in the upper half of a
	row). Instead, insert the taps after detailed placement, only in rows that
	already contain logic, in the free site immediately abutting a logic cell,
	so they share that cell's power pin run and its well.
	"""

	TAP = 'gf180mcu_fd_sc_mcu7t5v0__filltie'

	VDD_PINS = ('VDD', 'VNW')
	VSS_PINS = ('VSS', 'VPW')

	def __init__(self, reader):
		self.reader = reader
		self.block = reader.block
		self.dbu = self.block.getDbUnitsPerMicron()
		try:
			self.master = reader.db.findMaster(self.TAP)
		except AttributeError:
			self.master = None

	def _is_logic(self, inst):
		name = inst.getMaster().getName()
		return name.startswith('gf180mcu_fd_sc_') and not name.endswith('filltie')

	def _connect(self, inst, net_vdd, net_vss):
		for it in inst.getITerms():
			pin = it.getMTerm().getName()
			if pin in self.VDD_PINS and net_vdd is not None:
				it.connect(net_vdd)
			elif pin in self.VSS_PINS and net_vss is not None:
				it.connect(net_vss)

	def run(self):
		if self.master is None:
			print(f'WellTaps: {self.TAP} not in the library, skipping')
			return

		net_vdd = self.block.findNet('vdpwr')
		net_vss = self.block.findNet('vgnd')

		width = self.master.getWidth()

		# Group instances by row, and build each logic row's occupancy from
		# every instance that intersects the row band (macros span many rows).
		all_items = [(inst, inst.getBBox()) for inst in self.block.getInsts()]

		rows = {}
		for inst, bb in all_items:
			rows.setdefault(bb.yMin(), []).append((inst, bb))

		n_taps = 0
		n_skip = 0

		for y, items in sorted(rows.items()):
			logic = [
				(inst, bb) for inst, bb in items
				if self._is_logic(inst)
			]
			if not logic:
				continue

			row_h = logic[0][1].yMax() - logic[0][1].yMin()
			occ = [
				(bb.xMin(), bb.xMax()) for inst, bb in all_items
				if (bb.yMin() < y + row_h) and (bb.yMax() > y)
			]

			def free(x):
				x1 = x + width
				for (a, b) in occ:
					if (x < b) and (x1 > a):
						return False
				return True

			for inst, bb in logic:
				placed = None
				for x in (bb.xMax(), bb.xMin() - width):
					if free(x):
						placed = x
						break
				if placed is None:
					n_skip += 1
					continue

				name = f'TAP_WELL_{n_taps:d}'
				try:
					try:
						tap = odb.dbInst.create(self.block, self.master, name)
					except AttributeError:
						tap = odb.dbInst_create(self.block, self.master, name)
				except Exception as e:  # noqa: BLE001
					print(f'WellTaps: cannot create instances ({e!r}), skipping')
					return
				if tap is None:
					print(f'WellTaps: could not create {name}, stopping')
					n_skip += 1
					break
				try:
					tap.setOrient(inst.getOrient())
				except Exception:  # noqa: BLE001 - keep the default orientation
					pass
				tap.setLocation(placed, y)
				tap.setPlacementStatus('FIRM')
				self._connect(tap, net_vdd, net_vss)

				# Account for the new cell in this row's occupancy.
				occ.append((placed, placed + width))
				n_taps += 1

		print(f'WellTaps: {n_taps} taps inserted, {n_skip} logic cells '
			f'without a free abutting site')


class StdCellPower:

	"""Tie the top-level standard cells to the Metal5 power stripes.

	The tt_top glue logic sits in the macro-free bands between the branch
	rows, where Metal4 is free. A core-wide rail grid cannot be used here:
	pdngen's -followpins walks every row of the core, and a row inside a
	branch row has no legal vertical path up, because the two muxes of that
	row own Metal2/Metal3/Metal4 across almost the whole core width. pdngen
	gives up on those unconnectable rails with:

	  [PDN-0179] Unable to repair all channels.

	Without rails the cells are attached to the supplies only through
	set_global_connections, which is a purely logical connection. LVS then
	extracts every cell's power pin as its own net (_323_/VDD, _369_/VSS, ...)
	so the netlists do not match, and in silicon the logic would simply be
	unpowered.

	So connect the cells' own abutment strips instead: the VDD/VSS pins of
	GF180 cells contain a full-width 0.6um strip at the cell boundary, and
	adjacent cells abut, so the strip already forms the row rail. Put a
	Via1..Via3 stack inside that strip and a Metal4 riser up to the nearest
	Metal5 stripe of the same net. Drawing Metal1 over the whole pin bounding
	box (as an earlier version did) is wrong: the bbox also covers the cell's
	Metal1 signal pins, which shorts every input/output to the supply.
	"""

	NETS = ('vdpwr', 'vgnd')

	def __init__(self, reader):
		self.reader = reader

		tech = reader.db.getTech()
		self.grid = tech.getManufacturingGrid()

		self.rail_ly = tech.findLayer('Metal1')
		self.riser_ly = tech.findLayer('Metal4')

		self.v12 = ViaGenerator(reader, 'Via1_GEN_HH')
		self.v23 = ViaGenerator(reader, 'Via2_GEN_HH')
		self.v34 = ViaGenerator(reader, 'Via3_GEN_HH')
		self.v45 = ViaGenerator(reader, 'Via4_GEN_HH')

		self.riser_w = max(2 * self.riser_ly.getWidth(), 1)

		# Magic streams GDS on a 5nm grid (CIF scale 0.005um) while KLayout uses
		# 1nm, so any edge we place off that grid XORs as a 1nm sliver. Snap
		# everything we draw to it.
		self.snap = max(reader.block.getDbUnitsPerMicron() // 200, 1)

		self.macros = [
			inst.getBBox()
				for inst in reader.block.getInsts()
					if not inst.getMaster().getName().startswith('gf180mcu_fd_sc_')
		]

	def _align(self, v):
		return (v // self.grid) * self.grid

	def _snap_lo(self, v):
		return (v // self.snap) * self.snap

	def _snap_hi(self, v):
		return -((-v) // self.snap) * self.snap

	def _path_blocked(self, x, y0, y1):
		# Would a Metal4 riser from y0 to y1 at x pass through a macro ?
		for bb in self._macros_in(y0, y1):
			if bb.xMin() <= x <= bb.xMax():
				return True
		return False

	def _macros_in(self, y0, y1):
		# Macros whose vertical extent intersects [y0, y1]. Pre-filtering
		# keeps the riser search cheap (it runs for every candidate x).
		return [
			bb for bb in self.macros
				if (y1 > bb.yMin()) and (y0 < bb.yMax())
		]

	def _rect_blocked(self, x0, y0, x1, y1):
		# Would a Metal4 rectangle hit a macro ?
		for bb in self.macros:
			if (bb.xMin() < x1) and (bb.xMax() > x0) and \
					(bb.yMin() < y1) and (bb.yMax() > y0):
				return True
		return False

	def _rect_conflict(self, net_name, x0, y0, x1, y1, placed):
		# Same as _riser_conflict but for an arbitrary rectangle (the placed
		# entries already carry a lane of margin in x).
		for pnet, px0, px1, py0, py1 in placed:
			if pnet == net_name:
				continue
			if (px0 < x1) and (px1 > x0) and (py0 < y1) and (py1 > y0):
				return True
		return False

	def _sideways_riser(self, net_name, rx0, rx1, ry0, ry1, yc, stripe_ys,
			placed, lane, m1_half_w):
		"""Connect a rail that has no vertical path (e.g. boxed in by macros).

		The row between the two SRAMs has a macro directly above and below,
		so a purely vertical Metal4 riser cannot leave it. Run sideways on
		Metal4 inside the rail's own band (which carries only this net's
		strips) to a column with a clear vertical path, then go up to a
		stripe of the same net.
		"""
		band_h = max(ry1 - ry0, self.riser_w)
		yv = self._snap_lo(yc)
		by = (yv - band_h // 2, yv + band_h // 2)

		for side, end in ((1, rx1 - m1_half_w), (-1, rx0 + m1_half_w)):
			xv = self._snap_lo(end) if side > 0 else self._snap_hi(end)
			for d in range(1, 91):
				xh = self._snap_lo(xv + side * d * lane)

				hx0 = min(xv, xh) - self.riser_w // 2
				hx1 = max(xv, xh) + self.riser_w // 2
				if self._rect_blocked(hx0, by[0], hx1, by[1]):
					continue
				if self._rect_conflict(net_name, hx0, by[0], hx1, by[1], placed):
					continue

				for yt in sorted(stripe_ys, key=lambda y: abs(y - yc)):
					if self._path_blocked(xh, min(by[1], yt), max(by[0], yt)):
						continue

					yriser = self._snap_hi(yt)
					ya, yb = min(by[0], yriser), max(by[1], yriser)
					if self._riser_conflict(net_name, xh, ya, yb, placed, lane):
						continue

					return (xv, yv, xh, yriser, by, ya, yb)
		return None

	def _stripe_via(self, sw, net_name, x, y):
		# One Via4 per stripe location per net. Two vias whose cuts overlap
		# are merged differently by Magic and KLayout (1nm XOR slivers), so
		# keep them apart instead of stacking them.
		for vx, vy in self.via_points.get(net_name, ()):
			if abs(vx - x) < self.riser_w and abs(vy - y) < self.riser_w:
				return False
		self.via_points.setdefault(net_name, []).append((x, y))
		odb.createSBoxes(sw, self.v45.get(1, 1), [odb.Point(x, y)], 'STRIPE')
		return True

	def _riser_conflict(self, net_name, x, ya, yb, placed, lane):
		# Special wiring is not checked by the router, so a riser of one net
		# crossing a riser of the other would short vdpwr to vgnd in layout
		# while still passing DRC. Keep one lane of clearance between risers of
		# different nets over their common vertical extent.
		for pnet, px0, px1, py0, py1 in placed:
			if pnet == net_name:
				continue
			if (yb <= py0) or (ya >= py1):
				continue
			if (x + lane // 2 > px0) and (x - lane // 2 < px1):
				return True
		return False

	def _fix_width(self, a, b):
		# DEF writes a special-wire rectangle as a centreline plus a width.
		# Magic streams GDS on a 5nm grid while KLayout keeps 1nm, so a width
		# that is an odd number of grid steps puts the centreline on a half
		# nanometre and the two streams differ by 1nm along that edge (the XOR
		# slivers). Grow the far edge by one step to make the width even.
		if ((b - a) // self.grid) % 2:
			b += self.grid
		return a, b

	def _stripes(self, net):
		ys = set()
		for sw in net.getSWires():
			for w in sw.getWires():
				if w.isVia():
					continue
				if w.getTechLayer().getName() != 'Metal5':
					continue
				ys.add((w.yMin() + w.yMax()) // 2)
		return sorted(ys)

	def _strip_band(self, rects, height):
		"""Pick the cell-abutment power strip inside a pin's bounding box.

		The GF180 VDD/VSS pins are comb polygons: a ~0.6um-tall abutment strip
		at the top or bottom of the pin plus narrow fingers reaching into the
		cell. The strip is the part that abuts the neighbouring cells (a
		continuous rail along the row); the bounding box also covers the
		Metal1 signal pins (A1/A2/Z reach up to y=3.38 in the cell frame), so
		using the bbox shorts every signal pin to the supply.

		The abutment strip is the wide, short rectangle of the pin: the
		decomposed pin geometry contains it at the cell boundary while the
		fingers are narrow and tall. Pick the shortest rectangle that is at
		least half as wide as the widest one, which is orientation
		independent.
		"""
		maxw = max(r[3] - r[2] for r in rects)
		cands = [r for r in rects if (r[3] - r[2]) >= maxw // 2]
		w = min(cands, key=lambda r: r[1] - r[0])
		y0, y1 = w[0], w[1]
		if (y1 - y0) < height:
			mid = (y0 + y1) // 2
			y0 = mid - height // 2
			y1 = y0 + height
		return (y0, y1)

	def _runs(self):
		"""Abutment-strip runs, grouped per net and per site row.

		The GF180 VDD/VSS pins are combs: a ~0.6um-tall abutment strip at the
		cell boundary plus narrow fingers reaching into the cell. Only the
		strip is the row rail; the fingers are interior metal. Clustering
		every decomposed rectangle by y (as this used to) turns each finger
		into its own "rail" - a ~0.3um strip that can never hold a via - and
		that was 619 of the 629 rails reported "without a path".

		So reduce each cell's pin to its abutment strip first (per cell, not
		per row: a row mixes cell widths, and picking the band from the
		widest cell's geometry drops the narrow cells' strips), then cluster
		the strips into row rails.
		"""
		strip_h = 600 * self.reader.block.getDbUnitsPerMicron() // 1000

		per_net = {}
		for inst in self.reader.block.getInsts():
			if not inst.getMaster().getName().startswith('gf180mcu_fd_sc_'):
				continue
			for it in inst.getITerms():
				net = it.getNet()
				if net is None:
					continue
				if net.getName() not in self.NETS:
					continue
				rects = []
				for geom in it.getGeometries():
					layer, r = geom[0], geom[1]
					if hasattr(layer, 'getName') and layer.getName() != 'Metal1':
						continue
					rects.append(
						(r.yMin(), r.yMax(), r.xMin(), r.xMax())
					)
				if not rects:
					continue
				band = self._strip_band(rects, strip_h)
				keep = [
					r for r in rects
						if min(r[1], band[1]) > max(r[0], band[0])
				]
				if keep:
					per_net.setdefault(net.getName(), []).extend(keep)

		rows = {}
		for net_name, rects in per_net.items():
			rects.sort(key=lambda t: (t[0] + t[1]) // 2)
			clusters = []
			for r in rects:
				yc = (r[0] + r[1]) // 2
				if clusters:
					c = clusters[-1]
					if abs(((c[0] + c[1]) // 2) - yc) <= 2000:
						c[0] = min(c[0], r[0])
						c[1] = max(c[1], r[1])
						c[2].append(r)
						continue
				clusters.append([r[0], r[1], [r]])

			for idx, (cy0, cy1, rs) in enumerate(clusters):
				spans = [(x0, x1) for (y0, y1, x0, x1) in rs]
				rows[(net_name, idx)] = (spans, cy0, cy1)
		return rows

	def run(self):
		stripes = {}
		for net_name in self.NETS:
			net = self.reader.block.findNet(net_name)
			if net is not None:
				stripes[net_name] = self._stripes(net)

		if not any(stripes.values()):
			print('StdCellPower: no Metal5 power stripes found, skipping')
			return

		rows = self._runs()
		if not rows:
			print('StdCellPower: no standard cell power pins found, skipping')
			return

		# Riser lanes. Two risers of the same net may overlap, but a riser of
		# vdpwr and one of vgnd in the same column is a dead short between the
		# supplies, and special wiring bypasses the router's DRC checks. Place
		# every riser on a lane grid and keep one lane of clearance to the
		# other net.
		lane = max(2 * self.riser_w, 2 * self.grid)
		placed = []
		self.via_points = {}

		# The via must fit inside the cell's Metal1 abutment strip; use the
		# actual Metal1 footprint of the Via1 rather than the riser width.
		m1_half_w = (self.v12.cut_sz[0] + 2 * self.v12.bot_enc[0]) // 2

		# Build the rails (the strips) first: they are the riser search space.
		# The strips are part of the cells (adjacent cells abut into one rail),
		# so no Metal1 geometry is drawn here; only the via that takes the
		# strip up to Metal4.
		rails = []
		seen_rails = set()
		n_degenerate = 0

		for key in sorted(rows):
			spans, y0, y1 = rows[key]
			net_name = key[0]

			# Merge touching strips into one rail
			spans = sorted(spans)
			runs = []
			cx0, cx1 = spans[0]
			for x0, x1 in spans[1:]:
				if x0 <= (cx1 + 2 * self.grid):
					cx1 = max(cx1, x1)
				else:
					runs.append((cx0, cx1))
					cx0, cx1 = x0, x1
			runs.append((cx0, cx1))

			for x0, x1 in runs:
				rx0, rx1 = self._snap_lo(x0), self._snap_hi(x1)
				ry0, ry1 = self._snap_lo(y0), self._snap_hi(y1)
				if (rx1 - rx0) <= 0 or (ry1 - ry0) <= 0:
					n_degenerate += 1
					continue

				r = (net_name, rx0, ry0, rx1, ry1)
				if r in seen_rails:
					continue
				seen_rails.add(r)
				rails.append(r)

		n_rails = len(rails)
		n_risers = 0
		n_skipped = 0
		n_conflict = 0
		n_sideways = 0
		n_narrow = 0
		n_blocked = 0
		n_sideways_fail = 0

		for net_name, rx0, ry0, rx1, ry1 in rails:
			net = self.reader.block.findNet(net_name)
			yc = (ry0 + ry1) // 2

			# Candidate x positions inside the strip, on the lane grid,
			# starting in the middle and walking outwards.
			lo = self._snap_hi(rx0 + m1_half_w)
			hi = self._snap_lo(rx1 - m1_half_w)
			if hi < lo:
				n_skipped += 1
				n_narrow += 1
				continue

			kmax = (hi - lo) // lane
			if kmax < 0:
				kmax = 0
			k0 = kmax // 2
			ks = []
			for d in range(0, kmax + 1):
				ks.append(k0 + d)
				if d:
					ks.append(k0 - d)

			# Try the nearest stripes first; a farther stripe is sometimes the
			# only one reachable without crossing a macro row.
			stripe_order = sorted(
				stripes[net_name], key=lambda y: abs(y - yc)
			)

			found = None
			for k in ks:
				x = self._snap_lo(lo + k * lane)

				for yt in stripe_order:
					if self._path_blocked(x, min(yc, yt), max(yc, yt)):
						continue

					yvia = self._snap_lo(yc)
					yriser = self._snap_hi(yt)
					ya, yb = min(yvia, yriser), max(yvia, yriser)
					if (yb - ya) < self.riser_w:
						# The stripe is effectively at the rail. Center a
						# minimum-length riser on a grid multiple: an odd
						# half-grid centre puts both edges on a 2.5nm grid, and
						# Magic (5nm) and KLayout (1nm) then disagree by 1nm
						# (the remaining Metal4 XOR slivers).
						ym = (((ya + yb) // 2) // self.grid) * self.grid
						ya = ym - self.riser_w // 2
						yb = ya + self.riser_w

					if self._riser_conflict(net_name, x, ya, yb, placed, lane):
						n_conflict += 1
						continue

					found = (x, yvia, yriser, ya, yb)
					break

				if found is not None:
					break

			if found is None:
				n_blocked += 1
				side = self._sideways_riser(
					net_name, rx0, rx1, ry0, ry1, yc,
					stripes[net_name], placed, lane, m1_half_w,
				)
				if side is not None:
					xv, yv, xh, yriser, by, ya, yb = side
					sw = odb.dbSWire.create(net, "ROUTED")
					odb.createSBoxes(sw, self.riser_ly, [
						odb.Rect(min(xv, xh) - self.riser_w // 2, by[0],
							max(xv, xh) + self.riser_w // 2, by[1]),
						odb.Rect(xh - self.riser_w // 2, min(by[0], yriser),
							xh + self.riser_w // 2, max(by[1], yriser)),
					], "STRIPE")
					for vg in (self.v12, self.v23, self.v34):
						odb.createSBoxes(sw, vg.get(1, 1), [odb.Point(xv, yv)], "STRIPE")
					self._stripe_via(sw, net_name, xh, yriser)
					placed.append((net_name, min(xv, xh) - lane // 2,
						max(xv, xh) + lane // 2, ya, yb))
					n_sideways += 1
					n_risers += 1
					continue

			if found is None:
				n_skipped += 1
				n_sideways_fail += 1
				continue

			x, yvia, yriser, ya, yb = found
			placed.append((net_name, x - lane // 2, x + lane // 2, ya, yb))

			sw = odb.dbSWire.create(net, "ROUTED")
			odb.createSBoxes(sw, self.riser_ly, [
				odb.Rect(x - self.riser_w // 2, ya, x + self.riser_w // 2, yb)
			], "STRIPE")
			for vg in (self.v12, self.v23, self.v34):
				odb.createSBoxes(sw, vg.get(1, 1), [odb.Point(x, yvia)], "STRIPE")

			# One Via4 per (lane, stripe) even when several rails of this net
			# share the riser, so the cut arrays never overlap each other.
			self._stripe_via(sw, net_name, x, yriser)

			n_risers += 1

		print(f'StdCellPower: {n_rails} rails, {n_risers} risers '
			f'({n_sideways} sideways), {n_skipped} without a path '
			f'(narrow {n_narrow}, no vertical path {n_blocked}, '
			f'sideways failed {n_sideways_fail}), '
			f'{n_conflict} lane conflicts, {n_degenerate} degenerate')


class RingTie:
	"""Bridge the gaps in the core ring.

	pdngen emits the vdpwr ring's vertical segments in pieces: the left lane
	has 6 segments and the right lane 5, with ~221um gaps between them (the
	vgnd and vapwr rings are single segments). Every Metal5 stripe of a net
	terminates on that net's ring, so each gap splits the grid into an
	independent horizontal band: the extracted layout then has several
	"net vdpwr" fragments, and only the bands that happen to reach an edge
	pad are powered in silicon.

	Each net's vertical ring lane is exclusive - the rings are nested with
	2um gaps (vapwr 16.16..28.16, vgnd 30.16..42.16, vdpwr 44.16..56.16 on
	the left, mirrored on the right) - so a continuous bar on the lane can
	only touch the same net's own ring segments. A 12um bar is well below
	the 30um slotted-metal threshold.
	"""

	NETS = ('vdpwr', 'vgnd', 'vapwr')

	def __init__(self, reader):
		self.reader = reader
		self.tech = reader.db.getTech()
		self.m4 = self.tech.findLayer('Metal4')
		self.v45 = ViaGenerator(reader, 'Via4_GEN_HH')
		self.dbu = reader.block.getDbUnitsPerMicron()

		die = reader.block.getDieArea()
		self.x0, self.y0 = die.xMin(), die.yMin()
		self.x1, self.y1 = die.xMax(), die.yMax()

	def run(self):
		mid = (self.x0 + self.x1) // 2

		for net_name in self.NETS:
			net = self.reader.block.findNet(net_name)
			if net is None:
				continue

			segs = []
			for sw in net.getSWires():
				for w in sw.getWires():
					if w.isVia():
						continue
					if w.getTechLayer().getName() != 'Metal4':
						continue
					if w.getWireShapeType() != 'RING':
						continue
					segs.append(w)

			if not segs:
				continue

			for side, pred in (
				('l', lambda s: s.xMax() <= mid),
				('r', lambda s: s.xMin() >= mid),
			):
				lane = [s for s in segs if pred(s)]
				if not lane:
					continue

				x0 = min(s.xMin() for s in lane)
				x1 = max(s.xMax() for s in lane)

				# Bridge only the gaps between consecutive ring segments. A
				# continuous bar over the whole die height is wrong: the
				# decorative gf180mcu_ws_ip__* / tt_logo_* macros sit in the
				# die margin and their mask-art metal spans several ring lanes,
				# so a full-height bar would be shorted to the neighbouring
				# supplies through them. The gaps are at branch rows, well away
				# from the margins.
				lane.sort(key=lambda s: s.yMin())
				n_bridge = 0
				for a, b in zip(lane, lane[1:]):
					ya = a.yMax() - 1000
					yb = b.yMin() + 1000
					if yb <= ya:
						continue
					sw = odb.dbSWire.create(net, "ROUTED")
					odb.createSBoxes(sw, self.m4, [
						odb.Rect(x0, ya, x1, yb)
					], "RING")
					n_bridge += 1

				gaps = 0
				prev = None
				for s in lane:
					if prev is not None and s.yMin() > prev:
						gaps += 1
					prev = max(prev or 0, s.yMax())
				print(f'RingTie: {net_name}/{side} lane x={x0/self.dbu:.2f}..{x1/self.dbu:.2f}, '
					f'{len(lane)} segments, {gaps} gaps, {n_bridge} bridges')


class PadPowerStraps:
	"""Connect the wrapper's power pins to the grid.

	pdngen's `add_pdn_ring -connect_to_pads` produces nothing usable on this
	template: a geometric check of the DEF (and the extracted netlist) shows
	every top-level power pin isolated and the whole grid source-less.

	Left/right pins are ~24um-tall Metal3 rectangles at the die edge, so a
	Metal3 stub can reach the net's ring lane directly (each net's lane is
	exclusive, see RingTie) and a Via3 array lands on the continuous ring bar.

	Bottom/top pins have no lane next to them. Run a Metal3 strap just inside
	the die edge, below/above the pad pins, to the nearest ring lane: that
	region is in the macro-free margin. Each net gets its own y band; the
	power pads of the different nets are far apart in x, so the straps do not
	cross. A conflict check refuses any strap that would touch geometry of a
	different net.
	"""

	NETS = ('vdpwr', 'vgnd', 'vapwr')

	# y (um, inside the die) of the bottom strap of each net; the top strap is
	# mirrored. Only nets with bottom/top pins need one.
	BAND_Y = {'vgnd': 2.0, 'vapwr': 6.0, 'vdpwr': 10.0}
	BAND_H = 2.0

	def __init__(self, reader):
		self.reader = reader
		self.tech = reader.db.getTech()
		self.dbu = reader.block.getDbUnitsPerMicron()

		self.m3 = self.tech.findLayer('Metal3')
		self.v34 = ViaGenerator(reader, 'Via3_GEN_HH')

		self.snap = max(self.dbu // 200, 1)

		die = reader.block.getDieArea()
		self.x0, self.y0 = die.xMin(), die.yMin()
		self.x1, self.y1 = die.xMax(), die.yMax()

		# Ring lanes per net (same discovery as RingTie).
		self.lanes = {}
		for net_name in self.NETS:
			net = reader.block.findNet(net_name)
			if net is None:
				continue
			segs = []
			for sw in net.getSWires():
				for w in sw.getWires():
					if w.isVia():
						continue
					if w.getTechLayer().getName() != 'Metal4':
						continue
					if w.getWireShapeType() != 'RING':
						continue
					segs.append(w)
			if not segs:
				continue
			mid = (self.x0 + self.x1) // 2
			rv = {}
			for side, pred in (
				('l', lambda s: s.xMax() <= mid),
				('r', lambda s: s.xMin() >= mid),
			):
				lane = [s for s in segs if pred(s)]
				if lane:
					rv[side] = (
						min(s.xMin() for s in lane),
						max(s.xMax() for s in lane),
					)
			if rv:
				self.lanes[net_name] = rv

		# All Metal3 pin boxes of every other net, for the conflict check.
		self.pins = []
		for net in reader.block.getNets():
			for bterm in net.getBTerms():
				for bpin in bterm.getBPins():
					for box in bpin.getBoxes():
						try:
							ly = box.getTechLayer().getName()
						except (AttributeError, TypeError):
							continue
						if ly != 'Metal3':
							continue
						self.pins.append((
							net.getName(),
							(box.xMin(), box.yMin(), box.xMax(), box.yMax()),
						))

		self.drawn = []

	def _overlap(self, a, b):
		return (min(a[2], b[2]) > max(a[0], b[0])) and \
			(min(a[3], b[3]) > max(a[1], b[1]))

	def _conflict(self, net_name, rect):
		for other, r in self.pins:
			if other != net_name and self._overlap(rect, r):
				return other
		for other, r in self.drawn:
			if other != net_name and self._overlap(rect, r):
				return other
		return None

	def _add(self, net, rects, via=None, point=None):
		sw = odb.dbSWire.create(net, "ROUTED")
		odb.createSBoxes(sw, self.m3, [odb.Rect(*r) for r in rects], "STRIPE")
		if via is not None:
			odb.createSBoxes(sw, via, [odb.Point(*point)], "STRIPE")
		for r in rects:
			self.drawn.append((net.getName(), r))

	def _via_for(self, vw, vh):
		via = self.v34.get4sz_ext(vw, vh, bot_fit='xy', top_fit='xy')
		if via is None:
			via = self.v34.get(1, 1)
		return via

	def _free_span(self, net_name, x0, x1, y0, y1):
		"""Largest sub-interval of [y0, y1] not covered by another net's pin.

		A few power pads have a pad_raw signal pin at the same y (its metal
		sits just inside the die edge, inside the power pad's y range), so the
		full-height stub would short to it. Use the tallest clear part instead.
		"""
		# Keep a full Metal3 spacing to the neighbouring pins: butting right
		# against them produced "pad_raw[55] to vdpwr" spacing violations at
		# the die edge (pad_raw[55] is the clock).
		margin = 1000

		blocked = []
		for other, r in self.pins:
			if other == net_name:
				continue
			if (min(x1, r[2]) > max(x0, r[0])) and (min(y1, r[3]) > max(y0, r[1])):
				blocked.append((max(y0, r[1]) - margin, min(y1, r[3]) + margin))

		if not blocked:
			return (y0, y1)

		blocked.sort()
		free = []
		cur = y0
		for b0, b1 in blocked:
			if b0 > cur:
				free.append((cur, b0))
			cur = max(cur, b1)
		if y1 > cur:
			free.append((cur, y1))

		if not free:
			return None
		return max(free, key=lambda t: t[1] - t[0])

	def _strap_side(self, net_name, side, box):
		lx0, lx1 = self.lanes[net_name][side]
		lc = (lx0 + lx1) // 2

		py0 = (box.yMin() // self.snap) * self.snap
		py1 = -((-box.yMax()) // self.snap) * self.snap

		x0 = (min(box.xMin(), lx0) // self.snap) * self.snap
		x1 = -((-max(box.xMax(), lc)) // self.snap) * self.snap

		span = self._free_span(net_name, x0, x1, py0, py1)
		if span is None:
			return False
		py0, py1 = span

		# The via needs a couple of microns of height.
		if (py1 - py0) < 4 * self.dbu:
			print(f'PadPowerStraps: {net_name} {side} strap skipped, '
				f'no clear pad height')
			return False

		rect = (x0, py0, x1, py1)
		other = self._conflict(net_name, rect)
		if other is not None:
			print(f'PadPowerStraps: {net_name} {side} strap skipped, '
				f'would touch {other}')
			return False

		via = self._via_for(min(lx1 - lx0, x1 - x0), py1 - py0)
		self._add(
			self.reader.block.findNet(net_name),
			[rect],
			via,
			(lc, (py0 + py1) // 2),
		)
		return True

	def _strap_edge(self, net_name, side, box):
		band = int(self.BAND_Y[net_name] * self.dbu)
		if side == 't':
			band = self.y1 - band
		band_h = int(self.BAND_H * self.dbu)

		pc = (box.xMin() + box.xMax()) // 2
		lane = min(
			('l', 'r'),
			key=lambda s: abs(
				(self.lanes[net_name][s][0] + self.lanes[net_name][s][1]) // 2 - pc
			),
		)
		lx0, lx1 = self.lanes[net_name][lane]
		lc = (lx0 + lx1) // 2

		px0 = (box.xMin() // self.snap) * self.snap
		px1 = -((-box.xMax()) // self.snap) * self.snap

		# Jog from the pad pin to the band, then the run to the lane.
		jy0 = min(box.yMin() // self.snap * self.snap, band)
		jy1 = max(box.yMax() // self.snap * self.snap, band + band_h)
		jog = (px0, jy0, px1, jy1)

		rx0 = min(px0, lc)
		rx1 = max(px1, lc)
		run = (rx0, band, rx1, band + band_h)

		for r in (jog, run):
			other = self._conflict(net_name, r)
			if other is not None:
				print(f'PadPowerStraps: {net_name} {side} strap skipped, '
					f'would touch {other}')
				return False

		via = self._via_for(lx1 - lx0, band_h)
		self._add(
			self.reader.block.findNet(net_name),
			[jog, run],
			via,
			(lc, band + band_h // 2),
		)
		return True

	def run(self):
		n_side = n_edge = n_skip = 0

		for net_name in self.NETS:
			net = self.reader.block.findNet(net_name)
			if net is None:
				continue
			if net_name not in self.lanes:
				print(f'PadPowerStraps: no ring lane for {net_name}, skipping')
				continue

			for bterm in net.getBTerms():
				for bpin in bterm.getBPins():
					for box in bpin.getBoxes():
						try:
							ly = box.getTechLayer().getName()
						except (AttributeError, TypeError):
							continue
						if ly != 'Metal3':
							continue

						r = (box.xMin(), box.yMin(), box.xMax(), box.yMax())

						if r[0] < self.x0:
							side = 'l'
						elif r[2] > self.x1:
							side = 'r'
						elif r[1] < self.y0:
							side = 'b'
						elif r[3] > self.y1:
							side = 't'
						else:
							continue

						if side in ('l', 'r'):
							ok = self._strap_side(net_name, side, box)
							n_side += int(ok)
						else:
							ok = self._strap_edge(net_name, side, box)
							n_edge += int(ok)
						n_skip += int(not ok)

		print(f'PadPowerStraps: {n_side} side straps, {n_edge} edge straps, '
			f'{n_skip} skipped')


class RingPowerStrapper:

	def __init__(self, reader):
		# Save vars
		self.reader = reader

		# Find useful data
		self.tech = tech = reader.db.getTech()

		self.layer = tech.findLayer('Metal3')
		self.viagen = ViaGenerator(reader, 'Via3_GEN_HH')

	def find_ring_for_net(self, net):
		# Find all the boxes on met4
		boxes = []
		for sw in net.getSWires():
			for w in sw.getWires():
				# Skip vias
				if w.isVia():
					continue

				# Only ring
				if w.getWireShapeType() != 'RING':
					continue

				boxes.append(w)

		# There should be none or 4
		if len(boxes) == 0:
			return None

		# GF180's PDN ring is generated differently from SKY130's; it may not
		# have exactly four RING boxes on each power net. Skip those nets
		# rather than aborting the flow.
		if len(boxes) != 4:
			return None

		# Sort and return
		boxes_ver = sorted([b for b in boxes if b.getDX() < b.getDY()], key=lambda x:x.xMin())
		boxes_hor = sorted([b for b in boxes if b.getDX() > b.getDY()], key=lambda x:x.yMin())

		if len(boxes_ver) != 2 or len(boxes_hor) != 2:
			return None

		return {
			'l': boxes_ver[0],
			'r': boxes_ver[1],
			'b': boxes_hor[0],
			't': boxes_hor[1],
		}

	def complete_ring(self, net, ring):
		sw = odb.dbSWire.create(net, "ROUTED")
		for box in [ ring['b'], ring['t'] ]:
			odb.createSBoxes(sw, self.tech.findLayer('Metal4'), [odb.Rect(box.xMin(), box.yMin(), box.xMax(), box.yMax())], "RING")

	def strap_draw_lr(self, sw, sxl, sxr, rxl, rxr, yb, yt):
		# Stripe
		odb.createSBoxes(sw, self.layer, [odb.Rect(sxl, yb, sxr, yt)], "STRIPE")

		# Connecting via
		via = self.viagen.get4sz(rxr-rxl, yt-yb)

		rxm = (rxl + rxr) // 2
		ym  = ( yb +  yt) // 2
		odb.createSBoxes(sw, via, [odb.Point(rxm, ym)], "STRIPE")

	def strap_draw_tb(self, sw, xl, xr, syb, syt, ryb, ryt):
		# Stripe
		odb.createSBoxes(sw, self.layer, [odb.Rect(xl, syb, xr, syt)], "STRIPE")

		# Connecting via
		via = self.viagen.get4sz(xr-xl, ryt-ryb)

		xm  = ( xl +  xr) // 2
		rym = (ryb + ryt) // 2
		odb.createSBoxes(sw, via, [odb.Point(xm, rym)], "STRIPE")

	def strap_bterm(self, net, ring, sw, bterm):
		# Die area
		die = self.reader.block.getDieArea()

		# Scan all the boxes for that bterm and connect it
		# to the appropriate rail
		for bpin in  bterm.getBPins():
			for bbox in bpin.getBoxes():
				# All power pins are expected to be on met3
				if bbox.getTechLayer().getName() != 'Metal3':
					continue

				# Which side is the pin on ?
				if bbox.xMin() < die.xMin():
					# Left
					self.strap_draw_lr(sw,
						bbox.xMin(),      ring['l'].xMax(),
						ring['l'].xMin(), ring['l'].xMax(),
						bbox.yMin(),      bbox.yMax()
					)

				elif bbox.xMax() > die.xMax():
					# Right
					self.strap_draw_lr(sw,
						ring['r'].xMin(), bbox.xMax(),
						ring['r'].xMin(), ring['r'].xMax(),
						bbox.yMin(),      bbox.yMax()
					)

				elif bbox.yMin() < die.yMin():
					# Bottom
					self.strap_draw_tb(sw,
						bbox.xMin(),      bbox.xMax(),
						bbox.yMin(),      ring['b'].yMax(),
						ring['b'].yMin(), ring['b'].yMax(),
					)

				elif bbox.yMax() > die.yMax():
					# Top
					self.strap_draw_tb(sw,
						bbox.xMin(),      bbox.xMax(),
						ring['t'].yMin(), bbox.yMax(),
						ring['t'].yMin(), ring['t'].yMax(),
					)

				else:
					# ???
					continue

	def strap_net(self, net):
		# Find all the rings boxes
		ring = self.find_ring_for_net(net)
		if ring is None:
			return

		# Complete the ring with met4 on top/bottom
		self.complete_ring(net, ring)

		# Create new SWire for our straps
		sw = odb.dbSWire.create(net, "ROUTED")

		# Find all the BTerms
		for bterm in net.getBTerms():
			self.strap_bterm(net, ring, sw, bterm)

	def run(self):
		# Scan all power nets and check if they need strapping
		for net in self.reader.block.getNets():
			if net.getSigType() in ['POWER', 'GROUND']:
				self.strap_net(net)


class AnalogRouter:

	def __init__(self, reader, tti):
		# Save vars
		self.reader = reader
		self.tti    = tti

		# Create tech rules
		self.prepare_tech()

		# Find all analog switches
		self.asw = [
			inst
				for inst in self.reader.block.getInsts()
				if inst.getMaster().getName().startswith('tt_asw')
		]

		# Load route data file
		self.route_data = yaml.load(open('route_data.yaml'), yaml.FullLoader).get('analog', {})

	def prepare_tech(self):
		# Find tech and layers
		tech = self.reader.db.getTech()
		self.layer_bot = tech.findLayer('Metal3')
		self.layer_top = tech.findLayer('Metal4')
		self.via_sig   = ViaGenerator(self.reader, 'Via3_GEN_HH')

		# Create via for analog signal
		viagen = ViaGenerator(self.reader, 'Via3_GEN_HH')
		self.via = viagen.create(3, 3, 'analog_via')

		# Create via generator for power
		self.pwr_vg = ViaGenerator(self.reader, 'Via4_GEN_HH')

		# Create non-default rule
		self.ndr = ndr = odb.dbTechNonDefaultRule_create(self.reader.block, 'analog_track')
		for ln in [ 'Metal1', 'Metal2', 'Metal3', 'Metal4', 'Metal5' ]:
			ly = tech.findLayer(ln)
			lr = odb.dbTechLayerRule_create(ndr, ly)
			lr.setWidth(900)
			lr.setSpacing(2700)

	def _asw_find_pdn_stripe(self, net, y, above):
		# Scan all special wires on that net
		best_sb   = None
		best_dist = None

		for sw in net.getSWires():
			for sb in sw.getWires():
				# Must be horizontal non-via STRIPE
				if sb.isVia() or (sb.getWireShapeType() != 'STRIPE') or (sb.getDY() > sb.getDX()):
					continue

				# Distance
				d = ((sb.yMin() + sb.yMax()) // 2) - y

				if above ^ (d > 0):
					continue

				if (best_dist is None) or (abs(d) < abs(best_dist)):
					best_sb   = sb
					best_dist = d

		# Return result
		center = (best_sb.yMin() + best_sb.yMax()) // 2
		farend = best_sb.yMax() if above else best_sb.yMin()
		width  = best_sb.getDY()

		return center, farend, width

	def _asw_power_solo(self, asw):
		# Process each power pin
		for it in asw.getITerms():
			# Matching net
			net = it.getNet()

			# Only consider power/ground
			if it.getSigType() not in ['POWER', 'GROUND']:
				continue

			# Orientation, should we connect above or below ?
			orient = asw.getOrient()

			if orient in [ 'R0', 'MY' ]:
				above = False
			elif orient in [ 'R180', 'MX' ]:
				above = True
			else:
				raise RuntimeError('Unknown orientation of analog switch')

			# Bounding box of terminal
			bbox = it.getBBox()

			xl = bbox.xMin()
			xr = bbox.xMax()
			xc = bbox.xCenter()
			xw = bbox.dx()

			y  = bbox.yMin() if above else bbox.yMax()

			# Find PDN stripe
			pdn_center, pdn_farend, pdn_width = self._asw_find_pdn_stripe(net, y, above)

			# Prepare to add special routing
			sw = odb.dbSWire.create(net, "ROUTED")

			# Add via
				# Current viagen is too pessimistic and doesn't work with small connections
				# (doesn't know about preferred directions and such). So request a 1x5 via ...
			# via = self.pwr_vg.get4sz(xw, pdn_width)
			via = self.pwr_vg.get(1, 5)
			odb.createSBoxes(sw, via, [odb.Point(xc, pdn_center)], "STRIPE")

			# Extend the ITerm stripe to PDN
			odb.createSBoxes(sw, via.getBottomLayer(), [odb.Rect(xl, y, xr, pdn_farend)], "STRIPE")

	def _asw_power_pair(self, asw_bot, asw_top):
		# Process each power pin
		for it_bot in asw_bot.getITerms():
			# Matching net
			net = it_bot.getNet()

			# Only consider power/ground
			if it_bot.getSigType() not in ['POWER', 'GROUND']:
				continue

			# Get matching iterm
			it_top = asw_top.findITerm(it_bot.getMTerm().getName())

			# Coordinates
			bbox_bot = it_bot.getBBox()
			bbox_top = it_top.getBBox()

			xl = bbox_bot.xMin()
			xr = bbox_bot.xMax()
			xc = bbox_bot.xCenter()
			xw = bbox_bot.dx()

			yb = bbox_bot.yMin()
			yt = bbox_top.yMax()

			# Find PDN stripe
			pdn_center, pdn_farend, pdn_width = self._asw_find_pdn_stripe(net, yb, True)

			# Prepare to add special routing
			sw = odb.dbSWire.create(net, "ROUTED")

			# Add via
				# Current viagen is too pessimistic and doesn't work with small connections
				# (doesn't know about preferred directions and such). So request a 1x5 via ...
			# via = self.pwr_vg.get4sz(xw, pdn_width)
			via = self.pwr_vg.get(1, 5)
			odb.createSBoxes(sw, via, [odb.Point(xc, pdn_center)], "STRIPE")

			# Create strap
			odb.createSBoxes(sw, via.getBottomLayer(), [odb.Rect(xl, yb, xr, yt)], "STRIPE")


	def asw_power(self):
		# Group the analog switch per x coordinate
		xgrp = {}
		for inst in self.asw:
			xgrp.setdefault(inst.getLocation()[0], set()).add(inst)

		# Try to pair them
		asw_grp = []

		for grp in xgrp.values():
			while len(grp):
				# Pick one
				asw0 = grp.pop()

				# Scan the rest of the group for a potential pair
				for inst in grp:
					# Pair must have opposite orientation
					if inst.getOrient() == asw0.getOrient():
						continue

					# Pair must be close
					dist  = abs(inst.getLocation()[1] - asw0.getLocation()[1])
					limit = asw0.getBBox().getDY() * 3

					if dist < limit:
						asw1 = inst
						break
				else:
					# Nothing found
					asw_grp.append( (asw0, None) )
					continue

				# We found a pair, sort them as (bot, top)
				if asw0.getLocation()[1] > asw1.getLocation()[1]:
					asw_grp.append( (asw1, asw0) )
				else:
					asw_grp.append( (asw0, asw1) )

				# Also remove the match from the set
				grp.remove(asw1)

		# Process each group
		for asw0, asw1 in asw_grp:
			if asw1 is None:
				self._asw_power_solo(asw0)
			else:
				self._asw_power_pair(asw0, asw1)

	def asw_bus(self):
		# Offset
		OFFSET = 1350

		# Look at all analog switches to find extent
		#  First scan to group per block
		abi  = {}
		nets = set()

		for inst in self.asw:
			# Which block does it belong do
			blk = inst.getName().rsplit('.',1)[0]

			# Record position and and net
			it = inst.findITerm('bus')

			xpos = it.getAvgXY()[1]
			net  = it.getNet()

			bi = abi.setdefault(blk, ([], []))
			bi[0].append(xpos)
			bi[1].append(net.getName())

			nets.add(net.getName())

		#  Then for each net
		for net_name in nets:
			# Accumulate all relevant X positions
			xpl = []
			for blk, bi in abi.items():
				if net_name in bi[1]:
					xpl.extend(bi[0])

			# Get actual net, associated bterm and routing infos
			net = self.reader.block.findNet(net_name)
			bterm = net.getBTerms()[0]
			bbox  = bterm.getBBox()
			ri = self.route_data[bterm.getName()]

			# Actual IO position
			_, xp_bterm, yp_bterm = bterm.getFirstPinLocation()

			# Side of the IO
			w = self.ndr.getLayerRule(self.layer_bot).getWidth()
			mid = self.reader.block.getDieArea().dx() // 2

			if xp_bterm > mid:
				# IO goes right side
				xp_start = min(xpl) - OFFSET
				xp_pad   = bbox.xMin() - (w//2)

			else:
				# IO goes left side
				xp_start = max(xpl) + OFFSET
				xp_pad   = bbox.xMax() + (w//2)

			# Prepare for routing
			net.setNonDefaultRule(self.ndr)

			wire = odb.dbWire.create(net)

			encoder = odb.dbWireEncoder()
			encoder.begin(wire)

			# Create the 'bus' part
			encoder.newPath(self.layer_bot, 'FIXED', self.ndr.getLayerRule(self.layer_bot))

			encoder.addPoint(xp_start, ri[0])
			encoder.addPoint(ri[1],    ri[0])
			encoder.addPoint(ri[1],    yp_bterm)
			encoder.addPoint(xp_pad,   yp_bterm)

			encoder.newPath(self.layer_bot, 'FIXED')
			encoder.addPoint(xp_pad,   yp_bterm)
			encoder.addPoint(xp_bterm, yp_bterm)

			# Create all the stubs
			for inst in self.asw:
				# Connected to this net ?
				it = inst.findITerm('bus')

				if it.getNet().getName() != net_name:
					continue

				# Position of terminal
				_, xp_iterm, yp_iterm = it.getAvgXY()

				# Offset Shift
				if yp_iterm > ri[0]:
					xp_int = xp_iterm + OFFSET
					yp_int = yp_iterm - OFFSET * 2
				else:
					xp_int = xp_iterm - OFFSET
					yp_int = yp_iterm + OFFSET * 2

				# Create stub
				encoder.newPath(self.layer_top, 'FIXED', self.ndr.getLayerRule(self.layer_top))

				encoder.addPoint(xp_iterm, yp_iterm)
				encoder.addPoint(xp_iterm, yp_int)
				encoder.addPoint(xp_int,   yp_int)
				encoder.addPoint(xp_int,   ri[0])
				encoder.addVia(self.via)

			# Done routing
			encoder.end()

	def asw_mod(self):
		# Scan all switches
		for inst_asw in self.asw:
			# Get the module connection
			it_asw = inst_asw.findITerm('mod')

			# Get net
			net = it_asw.getNet()
			net.setNonDefaultRule(self.ndr)

			# Get the two iterms to connect
			its = net.getITerms()
			if len(its) != 2:
				raise RuntimeError('Too many module connections')

			it_mod = its[0] if (its[1].this == it_asw.this) else its[1]

			_, x0, y0 = it_mod.getAvgXY()
			_, x1, y1 = it_asw.getAvgXY()

			# Prepare to route
			wire = odb.dbWire.create(net)

			encoder = odb.dbWireEncoder()
			encoder.begin(wire)

			# Workaround for narrow pads
			# Remove in TT7 when analog template is updated ...
			w = self.ndr.getLayerRule(self.layer_top).getWidth()

			encoder.newPath(self.layer_top, 'FIXED')
			encoder.addPoint(x0, y0)
			y0 = (it_mod.getBBox().yMin() - (w//2)) if (y0 > y1) else (it_mod.getBBox().yMax() + (w//2))
			encoder.addPoint(x0, y0)

			# Path
			encoder.newPath(self.layer_top, 'FIXED', self.ndr.getLayerRule(self.layer_top))
			encoder.addPoint(x0, y0)

			if x0 != x1:
				ym = (y0 + y1) // 2
				encoder.addPoint(x0, ym)
				encoder.addPoint(x1, ym)

			encoder.addPoint(x1, y1)

			# Done routing
			encoder.end()

	def _asw_obs_hor(self, lst, y_min, y_max):
		# Init
		x_min = None
		x_max = None

		# Scan each
		for net_name in lst:
			net = self.reader.block.findNet(net_name)
			for it in net.getITerms():
				_, x, y = it.getAvgXY()

				x_min = min(x_min, x) if (x_min is not None) else x
				x_max = max(x_max, x) if (x_max is not None) else x
				y_min = min(y_min, y)
				y_max = max(y_max, y)

		if (x_min is None) or (x_max is None):
			return

		# Create obstructions
		odb.dbObstruction_create(self.reader.block,
			self.layer_bot,
			x_min, y_min,
			x_max, y_max,
		)

		odb.dbObstruction_create(self.reader.block,
			self.layer_top,
			x_min, y_min,
			x_max, y_max,
		)

	def _asw_obs_ver(self, lst):
		# Init
		x_min = None
		x_max = None
		y_min = None
		y_max = None

		# Scan each
		for net_name in lst:
			net = self.reader.block.findNet(net_name)
			bt = net.get1stBTerm()
			_, x, y = bt.getFirstPinLocation()

			x_min = min(x_min, x) if (x_min is not None) else x
			x_max = max(x_max, x) if (x_max is not None) else x
			y_min = min(y_min, y) if (y_min is not None) else y
			y_max = max(y_max, y) if (y_max is not None) else y

			yr = self.route_data[net_name][0]
			y_min = min(y_min, yr)
			y_max = max(y_max, yr)

		# Create obstruction
		odb.dbObstruction_create(self.reader.block,
			self.layer_bot,
			x_min, y_min,
			x_max, y_max,
		)

	def asw_obs(self):
		# Scan and groups the bus
		grp = []

		for net_name, net_rd in self.route_data.items():
			# Scan existing groups
			for i, (g_min, g_max, g_lst) in enumerate(grp):
				# Close ?
				if (abs(g_min - net_rd[0]) < 20000) or (abs(g_max - net_rd[0]) < 20000):
					g_lst.append(net_name)
					grp[i] = (
						min([g_min, net_rd[0]]),
						max([g_max, net_rd[0]]),
						g_lst
					)
					break

			else:
				# New group
				grp.append( (net_rd[0], net_rd[0], [net_name]) )

		# For each group, create horizontal and vertical obstructions
		for g_min, g_max, g_lst in grp:
			self._asw_obs_hor(g_lst, g_min, g_max)
			self._asw_obs_ver(g_lst)

	def asw_ena(self):
		# Scan all the user modules
		for um_inst in self.reader.instances:
			# Is this a user module ?
			if not um_inst.getName().endswith('.tt_um_I'):
				continue

			# Find matching mux
			ena_net = um_inst.findITerm('ena').getNet()

			mux_inst = None
			asw_insts = []

			for it in ena_net.getITerms():
				# Get info about attached block
				inst = it.getInst()
				master_name = inst.getMaster().getName()

				# Keep mux and analog switch
				if inst.getMaster().getName() == 'tt_mux':
					mux_inst = inst
					mux_it = it
				elif inst.getMaster().getName().startswith('tt_asw'):
					asw_insts.append(inst)

			if (mux_inst is None) or len(asw_insts) == 0:
				continue

			# X position of the mux (same as module)
			_, xp0, _ = mux_it.getAvgXY()

			# X position on the side of module away from PG
			if um_inst.getOrient() in ['R180', 'MY']:
				xp1 = um_inst.getBBox().xMin() - self.tti.layout.glb.margin.x // 2
			else:
				xp1 = um_inst.getBBox().xMax() + self.tti.layout.glb.margin.x // 2

			# Y postition between module and mux
			yl0 = sorted([
				mux_inst.getBBox().yMin(),
				mux_inst.getBBox().yMax(),
				um_inst.getBBox().yMin(),
				um_inst.getBBox().yMax(),
			])[1:3]

			yl0 = [ yl0[0], sum(yl0) // 2, yl0[1] ]

			# Y position between module and analog switch
			yp1 = sum(sorted([
				asw_insts[0].getBBox().yMin(),
				asw_insts[0].getBBox().yMax(),
				um_inst.getBBox().yMin(),
				um_inst.getBBox().yMax(),
			])[1:3]) // 2

			# X,Y positions of ASW terminal
			xl2 = []
			for inst in asw_insts:
				_, x, y = inst.findITerm('ctrl').getAvgXY()
				xl2.append(x)
				yp2 = y

			# Find which X position is "farthest" from xp1
			if xp1 > max(xl2):
				xp2 = min(xl2)
			else:
				xp2 = max(xl2)

			# Create routing
			wire = odb.dbWire.create(ena_net)

			encoder = odb.dbWireEncoder()
			encoder.begin(wire)

			encoder.newPath(self.layer_top, 'FIXED')
			encoder.addPoint(xp0, yl0[0])
			encoder.addPoint(xp0, yl0[2])

			encoder.newPath(self.layer_top, 'FIXED')
			encoder.addPoint(xp0, yl0[1])
			encoder.addPoint(xp1, yl0[1])
			encoder.addPoint(xp1, yp1)
			encoder.addVia(self.via_sig.get(1, 1))
			encoder.addPoint(xp2, yp1)

			for x in xl2:
				encoder.newPath(self.layer_bot, 'FIXED')
				encoder.addPoint(x, yp1)
				encoder.addPoint(x, yp2)

			encoder.end()

	def run(self):
		# GF180 has no analog switches; the Sky130-authored route_data.yaml
		# analog entries do not exist in this design, so skip the whole
		# analog router when no analog switch is present.
		if not self.asw:
			return
		self.asw_power()
		self.asw_bus()
		self.asw_mod()
		self.asw_obs()
		self.asw_ena()


@click.command()
@click_odb
def route(
	reader,
):

	# Load TinyTapeout
	tti = tt.TinyTapeout(modules=False)

	# Signal routing is left entirely to the router.
	#
	# The original sky130 flow pre-routed the branch spine and the
	# module/k01/pad buses by hand on Metal4, and relied on the sky130 tile
	# layout in which a module's pin sits directly above the mux pin it
	# belongs to. In this GF180 tile that alignment does not hold: the mux's
	# um_iw pins sit at x 1470..1488, y 2190.8, while the module's ui_in row
	# is at x ~1492, y 2038.9, with a *different* pin order along x. So every
	# hand-drawn connection became a short vertical stub that touched neither
	# pin (only 5 of 64 module inputs were connected in the extracted layout,
	# and those on the wrong slot), and because a net carrying a fixed wire
	# counts as pre-routed, TritonRoute then skipped those nets instead of
	# fixing them. Letting the router route them dropped LVS from 197 errors
	# to 35 - but it then collided with the hand-drawn spine, which is
	# invisible to the router (special/`dbWire FIXED` geometry is not part of
	# its database of routable shapes).
	#
	# All of these nets already have correct connectivity in the DEF, so none
	# of the pre-routing is needed. Keep only route_um_tieoffs(), which ties
	# off unused module inputs (that is a netlist change, not routing).
	r = Router(reader, tti)
	r.create_macro_obs()
	r.route_um_tieoffs()

	# Create the module power straps
	p = ModulePowerStrapper(reader, tti)
	p.run()

	# Add well taps next to the placed logic. This must run before the rails
	# are built so a tap shares the power pin run of the cell it abuts.
	p = WellTaps(reader)
	p.run()

	# Power the top level standard cells
	p = StdCellPower(reader)
	p.run()

	# Tie the hardened macros' power pins to the Metal5 stripes
	p = MacroPowerVias(reader)
	p.run()

	# Make the (segmented) core ring continuous, so the Metal5 stripes are not
	# split into independent horizontal bands
	p = RingTie(reader)
	p.run()

	# Connect the wrapper's power pins to the ring (pdngen's -connect_to_pads
	# does not produce usable geometry here)
	p = PadPowerStraps(reader)
	p.run()

	# No margin spines: a vertical Metal4 spine in the die margin cannot work
	# here. Each net's Metal5 stripes only extend as far as that net's ring, so
	# a spine outside the ring lands on no stripe at all, and the margin is
	# crossed by the three concentric rings (vapwr outermost, then vgnd, then
	# vdpwr). An earlier version did exactly that and shorted all three
	# supplies together. The ring lanes are tied up by RingTie instead, and
	# PadPowerStraps takes the pins to those lanes.

	# Create the ring power straps
	p = RingPowerStrapper(reader)
	p.run()

	# Analog router
	a = AnalogRouter(reader, tti)
	a.run()

if __name__ == "__main__":
	route()
