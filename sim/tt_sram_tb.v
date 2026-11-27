/*
 * tt_sram_tb.v
 *
 * End-to-end test of the shared SRAM for the GF180 build: a self-checking
 * tile (tt_um_sram_bist) in branch 11 / block 0 - the only branch of this
 * chip that both exists (TT_MUX_MASK) and carries the SRAM sideband
 * (TT_SRAM_MASK) - is selected through the real tt_ctrl protocol and then
 * writes and reads all 512 words through tt_mux, the spine and tt_top.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none
`timescale 1ns / 100ps

module tt_sram_tb;

	localparam integer MUX_ID = 11;
	localparam integer BLK_ID = 0;

	wire [43:0] io_in;
	wire [43:0] io_out;
	wire [43:0] io_oex;
	wire [43:0] io_ana;
	wire        k_zero;
	wire        k_one;

	reg ctrl_sel_rst_n = 1'b0;
	reg ctrl_sel_inc   = 1'b0;
	reg ctrl_ena       = 1'b0;
	reg u_clk          = 1'b0;
	reg u_rst_n        = 1'b0;

	tt_top dut_I (
`ifdef USE_POWER_PINS
		.VDPWR  (1'b1),
		.VAPWR  (1'b1),
		.VGND   (1'b0),
`endif
		.io_ana (io_ana),
		.io_in  (io_in),
		.io_out (io_out),
		.io_oex (io_oex),
		.k_zero (k_zero),
		.k_one  (k_one)
	);

	assign io_in[43:41] = 3'b000;
	assign io_in[40]    = ctrl_sel_rst_n;
	assign io_in[39]    = ctrl_sel_inc;
	assign io_in[38]    = ctrl_ena;
	assign io_in[37:16] = 22'd0;
	assign io_in[15]    = u_rst_n;
	assign io_in[14]    = u_clk;
	assign io_in[13:0]  = 14'd0;

	wire [7:0] uo = io_out[31:24];

	always #10 u_clk = ~u_clk;

	integer i;
	integer cycles;

	initial begin
		$dumpfile("tt_sram_tb.vcd");
		$dumpvars(0, tt_sram_tb);

		// Select the tile: reset the counter, pulse inc MUX_ID*32+BLK_ID times
		#50 ctrl_sel_rst_n = 1'b1;
		for (i = 0; i < MUX_ID * 32 + BLK_ID; i = i + 1) begin
			#5 ctrl_sel_inc = 1'b1;
			#5 ctrl_sel_inc = 1'b0;
		end
		#20 ctrl_ena = 1'b1;

		// Reset the user design (and the SRAM front-end) under clock
		repeat (4) @(posedge u_clk);
		#1 u_rst_n = 1'b1;

		cycles = 0;
		while (!uo[0] && cycles < 3000) begin
			@(posedge u_clk);
			cycles = cycles + 1;
		end

		#1;
		if (!uo[0])
			$fatal(1, "FAIL: BIST did not finish (uo=%b)", uo);
		if (dut_I.branch[MUX_ID].check_mask.block[BLK_ID].um_I.block_11_0.tt_um_I.n_checked !== 10'd512)
			$fatal(1, "FAIL: only %0d words checked",
				dut_I.branch[MUX_ID].check_mask.block[BLK_ID].um_I.block_11_0.tt_um_I.n_checked);
		if (!uo[1])
			$fatal(1, "FAIL: SRAM read-back mismatch, error bits = %h",
				dut_I.branch[MUX_ID].check_mask.block[BLK_ID].um_I.block_11_0.tt_um_I.err_bits);

		$display("PASS: shared SRAM BIST, 512 words x 32 bits, both banks, byte masks (%0d cycles)", cycles);
		$finish;
	end

	initial begin
		#2000000 $fatal(1, "FAIL: timeout");
	end

`ifdef INJECT_Q22_SHORT
	// Negative control: the original layout bug, sram_lo q[22] shorted to
	// vgnd. The BIST must fail with exactly bit 22 in its error bitmap.
	initial force dut_I.sram_q_lo[22] = 1'b0;
`endif
`ifdef INJECT_BANK_STUCK
	// Negative control: bank select stuck low, so the high bank is never
	// written and both halves of the address space alias onto sram_lo.
	initial force dut_I.sram_bank_d = 1'b0;
`endif

endmodule

`default_nettype wire
