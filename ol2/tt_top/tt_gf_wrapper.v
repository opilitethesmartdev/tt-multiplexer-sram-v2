/*
 * tt_gf_wrapper.v
 *
 * GF180MCU Top Level Wrapper for TinyTapeout Multiplexer
 *
 * Copyright (c) 2024
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none
`include "tt_defs.vh"

module tt_gf_wrapper (
`ifdef USE_POWER_PINS
	inout wire VDPWR,
	inout wire VAPWR,
	inout wire VGND,
`endif
	inout wire [73:0] pad_raw
);

	wire [43:0] io_ana;
	wire [43:0] io_in;
	wire [43:0] io_out;
	wire [43:0] io_oex;
	wire        k_zero;
	wire        k_one;

	// Control pads (0..5)
	assign io_in[43:38] = pad_raw[5:0];

	// Analog-capable pads
	assign io_in[37:32] = pad_raw[32:27];
	assign io_in[12:7]  = pad_raw[24:19];

	// Dedicated outputs (uo[7:0])
	assign io_in[31:24] = pad_raw[16:9];

	// Bidirectional IOs (uio[7:0])
	assign io_in[23:16] = pad_raw[44:37];

	// Dedicated inputs plus clock and reset
	assign io_in[15]   = pad_raw[54]; // u_rst_n
	assign io_in[14]   = pad_raw[55]; // u_clk
	assign io_in[13]   = pad_raw[53]; // ui_in[7]
	assign io_in[6:0]  = pad_raw[52:46]; // ui_in[6:0]

	// Expose the twelve analog-capable pads used by tt_top.
	// Keep both directions connected so user analog switches can pass
	// signals between the physical pads and the user modules.
	assign io_ana[12:7] = pad_raw[24:19];
	assign pad_raw[24:19] = io_ana[12:7];
	assign io_ana[37:32] = pad_raw[32:27];
	assign pad_raw[32:27] = io_ana[37:32];

	// Dedicated outputs are always enabled. The bidirectional pins need
	// individual enables: a vector conditional tests the entire OE vector,
	// and Yosys cannot reliably map inferred top-level tristates. Instantiate
	// the GF180 tristate cells explicitly so the enable exists in the layout.
	// These are core cells, NOT pad cells or ESD protection.
	assign pad_raw[16:9] = io_out[31:24];
	genvar uio_bit;
	generate
		for (uio_bit = 0; uio_bit < 8; uio_bit = uio_bit + 1) begin : uio_output_buffer
			gf180mcu_fd_sc_mcu7t5v0__bufz_12 cell_I (
				.I  (io_out[16 + uio_bit]),
				.EN (io_oex[16 + uio_bit]),
				.Z  (pad_raw[37 + uio_bit])
			);
		end
	endgenerate

	tt_top top_I (
`ifdef USE_POWER_PINS
		.VDPWR  (VDPWR),
		.VAPWR  (VAPWR),
		.VGND   (VGND),
`endif
		.io_ana (io_ana),
		.io_in  (io_in),
		.io_out (io_out),
		.io_oex (io_oex),
		.k_zero (k_zero),
		.k_one  (k_one)
	);

endmodule // tt_gf_wrapper

`default_nettype wire
