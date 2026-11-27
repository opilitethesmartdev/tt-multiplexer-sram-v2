/*
 * tt_sram_tb.v
 *
 * End-to-end test of the shared SRAM for the GF180 build: a self-checking
 * tile (tt_um_sram_bist) sits in every SRAM-capable slot (branches 3, 7, 11
 * and 13, blocks 0-7: 32 tiles). Each one in turn is selected through the
 * real tt_ctrl protocol and writes and reads all 512 words through tt_mux,
 * the spine and tt_top. Before each tile the memory is scrambled through a
 * backdoor, so a tile cannot pass by reading back an earlier tile's data.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none
`timescale 1ns / 100ps

module tt_sram_tb;

	localparam integer N_TILES = 32;
	integer tiles [0:N_TILES-1];	// mux_id * 32 + blk_id per tile
	integer t, w;
	initial begin
		for (t = 0; t < 8; t = t + 1) begin
			tiles[t]      = 3  * 32 + t;
			tiles[t + 8]  = 7  * 32 + t;
			tiles[t + 16] = 11 * 32 + t;
			tiles[t + 24] = 13 * 32 + t;
		end
	end

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

	localparam integer OTHER_MUX = 9;
	reg [63:0] sum_before;

	function [63:0] mem_sum(input dummy);
		integer w;
		begin
			mem_sum = 0;
			for (w = 0; w < 256; w = w + 1)
				mem_sum = mem_sum * 3 + dut_I.sram_lo_I.mem[w] + 7 * dut_I.sram_hi_I.mem[w];
		end
	endfunction

	initial begin
		$dumpfile("tt_sram_tb.vcd");
		$dumpvars(0, tt_sram_tb);

		for (t = 0; t < N_TILES; t = t + 1) begin
			// Scramble the memory so stale data from the previous tile
			// cannot make this one pass.
			for (w = 0; w < 256; w = w + 1) begin
				dut_I.sram_lo_I.mem[w] = $random;
				dut_I.sram_hi_I.mem[w] = $random;
			end

			// Select the tile: reset the counter, pulse inc mux*32+blk times
			ctrl_ena = 1'b0;
			u_rst_n = 1'b0;
			#20 ctrl_sel_rst_n = 1'b0;
			#20 ctrl_sel_rst_n = 1'b1;
			for (i = 0; i < tiles[t]; i = i + 1) begin
				#5 ctrl_sel_inc = 1'b1;
				#5 ctrl_sel_inc = 1'b0;
			end
			#20 ctrl_ena = 1'b1;

			// Reset the user design (and the SRAM front-end) under clock
			repeat (4) @(posedge u_clk);
			#1 u_rst_n = 1'b1;

			// The BIST must start from scratch: done set already would mean
			// we are looking at a stale or wrong tile.
			@(posedge u_clk);
			#1;
			if (uo[0])
				$fatal(1, "FAIL: branch %0d block %0d: done already set after reset",
					tiles[t] / 32, tiles[t] % 32);

			cycles = 0;
			while (!uo[0] && cycles < 3000) begin
				@(posedge u_clk);
				cycles = cycles + 1;
			end

			#1;
			if (!uo[0])
				$fatal(1, "FAIL: branch %0d block %0d: BIST did not finish (uo=%b)",
					tiles[t] / 32, tiles[t] % 32, uo);
			if (!uo[1])
				$fatal(1, "FAIL: branch %0d block %0d: SRAM read-back mismatch (uo=%b)",
					tiles[t] / 32, tiles[t] % 32, uo);
			if (cycles < 1024)
				$fatal(1, "FAIL: branch %0d block %0d: finished in %0d cycles, too fast for 512 writes + reads",
					tiles[t] / 32, tiles[t] % 32, cycles);
			$display("PASS: branch %0d block %0d: 512 words x 32 bits, both banks, byte masks (%0d cycles)",
				tiles[t] / 32, tiles[t] % 32, cycles);
		end
		$display("PASS: shared SRAM BIST from all %0d SRAM tiles", N_TILES);

		// Now select a project in a branch without SRAM (branch 9, block 0)
		// and run it: the SRAM bus must be driven to 0 (not float) and the
		// SRAM contents must not change.
		sum_before = mem_sum(0);
		ctrl_ena = 1'b0;
		#20 ctrl_sel_rst_n = 1'b0;
		#20 ctrl_sel_rst_n = 1'b1;
		for (i = 0; i < OTHER_MUX * 32; i = i + 1) begin
			#5 ctrl_sel_inc = 1'b1;
			#5 ctrl_sel_inc = 1'b0;
		end
		#20 ctrl_ena = 1'b1;
		repeat (200) @(posedge u_clk);
		#1;
		if (dut_I.spine_top_sram_ow !== {`TT_SRAM_OW{1'b0}})
			$fatal(1, "FAIL: SRAM spine not held low while another project runs: %b",
				dut_I.spine_top_sram_ow);
		if (dut_I.sram_ow !== {`TT_SRAM_OW{1'b0}})
			$fatal(1, "FAIL: SRAM request not zero while another project runs: %b",
				dut_I.sram_ow);
		if (mem_sum(0) !== sum_before)
			$fatal(1, "FAIL: SRAM contents changed while another project ran");
		$display("PASS: SRAM bus held low and contents intact while branch %0d runs", OTHER_MUX);
		$display("ALL PASS");
		$finish;
	end

	initial begin
		#50000000 $fatal(1, "FAIL: timeout");
	end

`ifdef INJECT_Q22_SHORT
	// Negative control: the original layout bug, sram_lo q[22] shorted to
	// vgnd. The BIST must fail with exactly bit 22 in its error bitmap.
	initial force dut_I.sram_q_lo[22] = 1'b0;
`endif
`ifdef INJECT_SEL_STUCK
	// Negative control: the SRAM branch decode stuck "selected", so the
	// keeper never holds the spine and the floating bus reaches the SRAM.
	initial force dut_I.sram_sel_top = 1'b1;
`endif
`ifdef INJECT_BANK_STUCK
	// Negative control: bank select stuck low, so the high bank is never
	// written and both halves of the address space alias onto sram_lo.
	initial force dut_I.sram_bank_d = 1'b0;
`endif

endmodule

`default_nettype wire
