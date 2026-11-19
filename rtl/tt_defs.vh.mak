/*
 * tt_defs.vh
 *
 * Shared defines
 *
 * Copyright (c) 2023 Sylvain Munaut <tnt@246tNt.com>
 * SPDX-License-Identifier: Apache-2.0
 */

`define TT_G_X  ${cfg.tt.grid.x}
`define TT_G_Y  ${cfg.tt.grid.y}

`define TT_N_AE ${cfg.tt.uio.ae}
`define TT_N_AU ${cfg.tt.uio.au}
`define TT_N_IO ${cfg.tt.uio.io}
`define TT_N_O  ${cfg.tt.uio.o}
`define TT_N_I  ${cfg.tt.uio.i}

<%
sram = getattr(cfg.tt, 'sram', None)
sram_addr = sram.addr_width if sram else 0
sram_data = sram.data_width if sram else 0
sram_wmask = sram.wmask_width if sram else 0
sram_ow = sram_addr + sram_data + sram_wmask + 2
%>
`define TT_SRAM_ADDR  ${sram_addr}
`define TT_SRAM_DATA  ${sram_data}
`define TT_SRAM_WMASK ${sram_wmask}
`define TT_SRAM_OW    ${sram_ow}
`define TT_SRAM_IW    ${sram_data}

`define TT_TECH_${cfg.pdk.tech.upper()}

`ifdef TT_TECH_SKY130
`define OE_POLARITY_NEGATIVE
`endif


<%
mux_mask = 0
if hasattr(cfg.tt, 'analog'):
	for grp in cfg.tt.analog:
		for mux_id in grp['mux_id']:
			mux_mask |= 1 << mux_id
if hasattr(cfg.tt, 'huge_modules'):
	for mux_id in cfg.tt.huge_modules.mux_id:
		mux_mask |= 1 << mux_id
%>
`define TT_MUX_MASK ${cfg.tt.grid.y}'h${'{:X}'.format(mux_mask)}
