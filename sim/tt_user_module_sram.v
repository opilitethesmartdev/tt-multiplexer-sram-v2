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
		{ 16'd11, 16'd0 }:
		begin : block_11_0
`ifdef USE_POWER_PINS
			wire l_vdpwr;
			wire l_vapwr;
`endif
			tt_um_sram_bist tt_um_I (
`ifdef USE_POWER_PINS
				.VDPWR   (l_vdpwr),
				.VAPWR   (l_vapwr),
				.VGND    (VGND),
`endif
				.uio_in  (uio_in),
				.uio_out (uio_out),
				.uio_oe  (uio_oe),
				.uo_out  (uo_out),
				.ui_in   (ui_in),
				.ena     (ena),
				.clk     (clk),
				.rst_n   (rst_n)
				,
				.sram_cs    (sram_cs),
				.sram_we    (sram_we),
				.sram_wmask (sram_wmask),
				.sram_addr  (sram_addr),
				.sram_wdata (sram_wdata),
				.sram_rdata (sram_rdata)
			);
`ifdef USE_POWER_PINS
			assign l_vdpwr = VDPWR;
`endif
`ifdef USE_POWER_PINS
			assign l_vapwr = VAPWR;
`endif
		end
		default: begin
			// Tie-off
			assign {sram_cs, sram_we, sram_wmask, sram_addr, sram_wdata, uio_oe, uio_out, uo_out} = { N_OW{k_zero} };
		end
		endcase
	endgenerate

endmodule // tt_user_module

`default_nettype wire

