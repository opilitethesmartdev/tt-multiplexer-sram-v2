/*
 * Logical stub for a user macro using the common Arrakeen SRAM interface.
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

(* blackbox *)
module {mod_name} (
	input  wire VGND,
	input  wire VDPWR,
	input  wire VAPWR,
	inout  wire [7:0] ua,
	input  wire [7:0] ui_in,
	output wire [7:0] uo_out,
	input  wire [7:0] uio_in,
	output wire [7:0] uio_out,
	output wire [7:0] uio_oe,
	input  wire       ena,
	input  wire       clk,
	input  wire       rst_n,
	output wire       sram_cs,
	output wire       sram_we,
	output wire [3:0] sram_wmask,
	output wire [8:0] sram_addr,
	output wire [31:0] sram_wdata,
	input  wire [31:0] sram_rdata
);
endmodule // {mod_name}

`default_nettype wire
