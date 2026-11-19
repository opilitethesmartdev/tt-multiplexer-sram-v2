/*
 * tt_user_module.v
 *
 * Wrapper to instanciate correct user module according to
 * grid position.
 *
 * Also maps signals to more "human" names
 *
 * Copyright (c) 2023 Sylvain Munaut <tnt@246tNt.com>
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none
`include "tt_defs.vh"

module tt_user_module #(
	// Logical  Position
	parameter integer MUX_ID = 0,
	parameter integer BLK_ID = 0,

	// Config
	parameter integer N_AE   = 12,
	parameter integer N_AU   = 8,
	parameter integer N_IO   = 8,
	parameter integer N_O    = 8,
	parameter integer N_I    = 10,

	// auto-set
	parameter integer N_OW = N_O + N_IO * 2 + `TT_SRAM_OW,
	parameter integer N_IW = N_I + N_IO + `TT_SRAM_IW
)(
`ifdef USE_POWER_PINS
	input  wire VDPWR,
	input  wire VAPWR,
	input  wire VGND,
`endif
	inout  wire  [N_AE-1:0] ana,
	output wire  [N_OW-1:0] ow,
	input  wire  [N_IW-1:0] iw,
	input  wire             ena,
	input  wire             k_zero,
	input  wire             pg_ena
);

	wire [N_AU-1:0] ua;
	wire [7:0] uio_in;
	wire [7:0] uio_out;
	wire [7:0] uio_oe;
	wire [7:0] uo_out;
	wire [7:0] ui_in;
	wire       clk;
	wire       rst_n;

	wire sram_cs;
	wire sram_we;
	wire [`TT_SRAM_WMASK-1:0] sram_wmask;
	wire [`TT_SRAM_ADDR-1:0] sram_addr;
	wire [`TT_SRAM_DATA-1:0] sram_wdata;
	wire [`TT_SRAM_DATA-1:0] sram_rdata;

	assign { sram_rdata, uio_in, ui_in, rst_n, clk } = iw;
	assign ow = { sram_cs, sram_we, sram_wmask, sram_addr, sram_wdata, uio_oe, uio_out, uo_out };

	generate
		case ({MUX_ID[15:0], BLK_ID[15:0]})
% for (mux_id, blk_id), mod in grid.items():
		{ 16'd${mux_id}, 16'd${blk_id} }:
		begin : block_${mux_id}_${blk_id}
%  if mod.common_sram:
			assign {sram_cs, sram_we, sram_wmask, sram_addr, sram_wdata, uio_oe, uio_out, uo_out} = {N_OW{k_zero}};
%  else:
%   if not mod.uses_sram:
			assign {sram_cs, sram_we, sram_wmask, sram_addr, sram_wdata} = {`TT_SRAM_OW{k_zero}};
%   endif
`ifdef USE_POWER_PINS
			wire l_vdpwr;
			wire l_vapwr;
`endif
			tt_um_${mod.name} tt_um_I (
`ifdef USE_POWER_PINS
				.VDPWR   (l_vdpwr),
				.VAPWR   (l_vapwr),
				.VGND    (VGND),
`endif
%  if mod.analog:
				.ua      (ua),
%  endif
				.uio_in  (uio_in),
				.uio_out (uio_out),
				.uio_oe  (uio_oe),
				.uo_out  (uo_out),
				.ui_in   (ui_in),
				.ena     (ena),
				.clk     (clk),
				.rst_n   (rst_n)
%   if mod.uses_sram:
				,
				.sram_cs    (sram_cs),
				.sram_we    (sram_we),
				.sram_wmask (sram_wmask),
				.sram_addr  (sram_addr),
				.sram_wdata (sram_wdata),
				.sram_rdata (sram_rdata)
%   endif
			);
%  if mod.analog:
%   for (pin_int, pin_ext) in mod.analog.items():
			${mod.asw_module} tt_asw_${pin_int}_I (
`ifdef USE_POWER_PINS
				.VDPWR   (VDPWR),
				.VAPWR   (VAPWR),
				.VGND    (VGND),
`endif
				.mod     (ua[${pin_int}]),
				.bus     (ana[${pin_ext}]),
				.ctrl	 (ena)
			);
%   endfor
%  endif
%  if mod.pg_vdd_module is not None:
			${mod.pg_vdd_module} tt_pg_vdd_I (
`ifdef USE_POWER_PINS
				.GPWR    (l_vdpwr),
				.VPWR    (VDPWR),
				.VGND    (VGND),
`endif
				.ctrl    (pg_ena)
			);
%  else:
`ifdef USE_POWER_PINS
			assign l_vdpwr = VDPWR;
`endif
%  endif
%  if mod.pg_vaa_module is not None:
			${mod.pg_vaa_module} tt_pg_vaa_I (
`ifdef USE_POWER_PINS
				.GAPWR   (l_vapwr),
				.VAPWR   (VAPWR),
				.VDPWR   (VDPWR),
				.VGND    (VGND),
`endif
				.ctrl    (pg_ena)
			);
%  else:
`ifdef USE_POWER_PINS
			assign l_vapwr = VAPWR;
`endif
%  endif
		end
%  endif
% endfor
		default: begin
			// Tie-off
			assign {sram_cs, sram_we, sram_wmask, sram_addr, sram_wdata, uio_oe, uio_out, uo_out} = { N_OW{k_zero} };
		end
		endcase
	endgenerate

endmodule // tt_user_module

`default_nettype wire
