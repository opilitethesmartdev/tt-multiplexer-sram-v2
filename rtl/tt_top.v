/*
 * tt_top.v
 *
 * Top level
 *
 * Copyright (c) 2023 Sylvain Munaut <tnt@246tNt.com>
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none
`include "tt_defs.vh"

module tt_top #(
	parameter integer N_PADS = 44,
	parameter integer G_X  = `TT_G_X,
	parameter integer G_Y  = `TT_G_Y,
	parameter integer N_AE = `TT_N_AE,
	parameter integer N_AU = `TT_N_AU,
	parameter integer N_IO = `TT_N_IO,
	parameter integer N_O  = `TT_N_O,
	parameter integer N_I  = `TT_N_I,
	parameter [G_Y-1:0] MUX_MASK = `TT_MUX_MASK
)(
	// Power
`ifdef USE_POWER_PINS
	input wire VDPWR,
	input wire VAPWR,
	input wire VGND,
`endif

	// IOs
	inout  wire [N_PADS-1:0] io_ana,
	input  wire [N_PADS-1:0] io_in,
	output wire [N_PADS-1:0] io_out,
	output wire [N_PADS-1:0] io_oex,	/* Polarity is tech dependent */

	// Convenient constants for top-level tie-offs
	output wire k_zero,
	output wire k_one
);

	localparam integer N_SRAM_OW = `TT_SRAM_OW;
	localparam integer N_SRAM_IW = `TT_SRAM_IW;

	// Branches whose mux carries the shared SRAM sideband. The rest keep the
	// plain mux and leave the sideband unconnected, which keeps ~79 wires per
	// disabled branch out of the routing problem.
	localparam [G_Y-1:0] SRAM_MASK = `TT_SRAM_MASK;

	localparam integer S_OW = N_O + N_IO * 2 + 2;
	localparam integer S_IW = N_I + N_IO + 9 + 1 + 2;

	localparam integer U_OW = N_O + N_IO * 2 + N_SRAM_OW;
	localparam integer U_IW = N_I + N_IO + N_SRAM_IW;


	// Signals
	// -------

	// Pads
	wire      [5:0] pad_ctl_in;
	wire      [5:0] pad_ctl_out;
	wire      [5:0] pad_ctl_oex;

	wire [N_IO-1:0] pad_uio_in;
	wire [N_IO-1:0] pad_uio_out;
	wire [N_IO-1:0] pad_uio_oex;

	wire  [N_O-1:0] pad_uo_in;
	wire  [N_O-1:0] pad_uo_out;
	wire  [N_O-1:0] pad_uo_oex;

	wire  [N_I-1:0] pad_ui_in;
	wire  [N_I-1:0] pad_ui_out;
	wire  [N_I-1:0] pad_ui_oex;

	wire [N_AE-1:0] pad_ana_in;
	wire [N_AE-1:0] pad_ana_out;
	wire [N_AE-1:0] pad_ana_oex;
	wire [N_AE-1:0] pad_ana_analog;

	// Vertical spine
	wire  [S_OW-1:0] spine_top_ow;
	wire  [S_IW-1:0] spine_top_iw;

	wire  [S_OW-1:0] spine_bot_ow;
	wire  [S_IW-1:0] spine_bot_iw;

	// The SRAM bus bypasses tt_ctrl; only the selected-side control crosses it.
	wire [N_SRAM_OW-1:0] spine_top_sram_ow;
	wire [N_SRAM_OW-1:0] spine_bot_sram_ow;
	wire sram_side_sel;

	// SRAM branch decode, per branch and per spine side
	wire [G_Y-1:0] sram_branch_match;
	wire sram_sel_top;
	wire sram_sel_bot;

	// Common SRAM interface
	wire [N_SRAM_OW-1:0] sram_ow;
	wire [N_SRAM_IW-1:0] sram_iw;
	wire sram_cs;
	wire sram_we;
	wire [`TT_SRAM_WMASK-1:0] sram_wmask;
	wire [`TT_SRAM_ADDR-1:0] sram_addr;
	wire [`TT_SRAM_DATA-1:0] sram_wdata;
	wire [`TT_SRAM_WMASK-1:0] sram_we_lo;
	wire [`TT_SRAM_WMASK-1:0] sram_we_hi;
	wire [`TT_SRAM_DATA-1:0] sram_q_lo;
	wire [`TT_SRAM_DATA-1:0] sram_q_hi;
	reg sram_bank_d;
	reg sram_cs_d;
	reg [`TT_SRAM_WMASK-1:0] sram_we_lo_d;
	reg [`TT_SRAM_WMASK-1:0] sram_we_hi_d;
	reg [`TT_SRAM_DATA-1:0] sram_wdata_d;

	// Control signals
	wire ctrl_sel_rst_n;
	wire ctrl_sel_inc;
	wire ctrl_ena;


	// Pad connections
	// ---------------

	// Split in groups
	assign {
		pad_ctl_in,
		pad_ana_in[11:6],
		pad_uo_in,
		pad_uio_in,
		pad_ui_in[1],	// u_rst
		pad_ui_in[0],	// u_clk
		pad_ui_in[9],
		pad_ana_in[5:0],
		pad_ui_in[8:2]
	} = io_in;

	assign io_out = {
		pad_ctl_out,
		pad_ana_out[11:6],
		pad_uo_out,
		pad_uio_out,
		pad_ui_out[1],	// u_rst
		pad_ui_out[0],	// u_clk
		pad_ui_out[9],
		pad_ana_out[5:0],
		pad_ui_out[8:2]
	};

	assign io_oex = {
		pad_ctl_oex,
		pad_ana_oex[11:6],
		pad_uo_oex,
		pad_uio_oex,
		pad_ui_oex[1],	// u_rst
		pad_ui_oex[0],	// u_clk
		pad_ui_oex[9],
		pad_ana_oex[5:0],
		pad_ui_oex[8:2]
	};

	assign pad_ana_analog = {
		io_ana[37:32],
		io_ana[12:7]
	};

	// Tie-offs
		// Control
	assign pad_ctl_oex    = { 6{k_one} };
	assign pad_ctl_out    = { 6{k_one} };

	assign ctrl_sel_rst_n = pad_ctl_in[2];
	assign ctrl_sel_inc   = pad_ctl_in[1];
	assign ctrl_ena       = pad_ctl_in[0];

		// Output enables
`ifdef OE_POLARITY_NEGATIVE
	assign pad_uo_oex  = { N_O  {k_zero} };
	assign pad_ui_oex  = { N_I  {k_one} };
	assign pad_ana_oex = { N_AE {k_one} };
`else
	assign pad_uo_oex  = { N_O  {k_one} };
	assign pad_ui_oex  = { N_I  {k_zero} };
	assign pad_ana_oex = { N_AE {k_zero} };
`endif

		// Output signal
	assign pad_ui_out  = { N_I{k_one} };
	assign pad_ana_out = { N_AE{k_one} };


	// Controller
	// ----------

	(* blackbox *)
	tt_ctrl
`ifdef SIM
	#(
		.N_I  (N_I),
		.N_O  (N_O),
		.N_IO (N_IO)
	)
`endif
	ctrl_I (
`ifdef USE_POWER_PINS
		.VDPWR          (VDPWR),
		.VGND           (VGND),
`endif
		.pad_uio_in     (pad_uio_in),
		.pad_uio_out    (pad_uio_out),
		.pad_uio_oex    (pad_uio_oex),
		.pad_uo_out     (pad_uo_out),
		.pad_ui_in      (pad_ui_in),
		.spine_top_ow   (spine_top_ow),
		.spine_top_iw   (spine_top_iw),
		.spine_bot_ow   (spine_bot_ow),
		.spine_bot_iw   (spine_bot_iw),
		.sram_side_sel  (sram_side_sel),
		.ctrl_sel_rst_n (ctrl_sel_rst_n),
		.ctrl_sel_inc   (ctrl_sel_inc),
		.ctrl_ena       (ctrl_ena),
		.k_one          (k_one),
		.k_zero         (k_zero)
	);


	// Common Arrakeen SRAM
	// --------------------

	// Each SRAM-capable mux drives its request onto the shared spine through
	// tri-state buffers that are only enabled while its branch is selected.
	// Whenever any other project is selected, nobody drives the bus: before
	// this, the floating spine went straight into the SRAM glue and the
	// SRAM's address pins (random writes, floating CMOS inputs).
	//  - Decode which SRAM branch is selected, exactly like tt_mux does
	//    (si_ena && si_sel[8:5] == branch address), and only accept a
	//    request from a selected SRAM branch.
	//  - Hold each side's bus low with weak tri-state drivers while no
	//    SRAM branch on that side is selected (the mux's own bus_pull
	//    technique), so the wires never float.
	localparam [G_Y-1:0] ODD_BRANCHES  = {(G_Y/2){2'b10}};
	localparam [G_Y-1:0] EVEN_BRANCHES = {(G_Y/2){2'b01}};

	assign sram_sel_top = |(sram_branch_match & ODD_BRANCHES);
	assign sram_sel_bot = |(sram_branch_match & EVEN_BRANCHES);

	// The spine SRAM bus is a long net driven from a far mux; buffer it
	// where it enters tt_top so the request decode sees a sharp edge (the
	// raw net into a nand4_1 was 8 ns at 3.3V slow corner).
	wire [N_SRAM_OW-1:0] spine_top_sram_ow_b;
	wire [N_SRAM_OW-1:0] spine_bot_sram_ow_b;

	genvar r;
	generate
		for (r=0; r<N_SRAM_OW; r=r+1) begin : sram_rx
`ifdef SIM
			assign spine_top_sram_ow_b[r] = spine_top_sram_ow[r];
			assign spine_bot_sram_ow_b[r] = spine_bot_sram_ow[r];
`elsif FORMAL
			assign spine_top_sram_ow_b[r] = spine_top_sram_ow[r];
			assign spine_bot_sram_ow_b[r] = spine_bot_sram_ow[r];
`else
			if (|(SRAM_MASK & ODD_BRANCHES)) begin : top
				(* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_8 buf_I (.I (spine_top_sram_ow[r]), .Z (spine_top_sram_ow_b[r]));
			end else begin : top_tie
				assign spine_top_sram_ow_b[r] = 1'b0;
			end
			if (|(SRAM_MASK & EVEN_BRANCHES)) begin : bot
				(* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_8 buf_I (.I (spine_bot_sram_ow[r]), .Z (spine_bot_sram_ow_b[r]));
			end else begin : bot_tie
				assign spine_bot_sram_ow_b[r] = 1'b0;
			end
`endif
		end
	endgenerate

	assign sram_ow = ctrl_ena
		? (sram_sel_top ? spine_top_sram_ow_b :
		   sram_sel_bot ? spine_bot_sram_ow_b : {N_SRAM_OW{1'b0}})
		: {N_SRAM_OW{1'b0}};

	genvar k;
	generate
		if (|(SRAM_MASK & ODD_BRANCHES)) begin : sram_keep_top
			for (k=0; k<N_SRAM_OW; k=k+1) begin : keep_bit
`ifdef FORMAL
				// formal models the mux outputs as the only drivers
`elsif SIM
				assign spine_top_sram_ow[k] = sram_sel_top ? 1'bz : 1'b0;
`else
				gf180mcu_fd_sc_mcu7t5v0__bufz_1 keep_I (
					.I  (1'b0),
					.EN (~sram_sel_top),
					.Z  (spine_top_sram_ow[k])
				);
`endif
			end
		end else begin : sram_no_top
			assign spine_top_sram_ow = {N_SRAM_OW{1'b0}};
		end
		if (|(SRAM_MASK & EVEN_BRANCHES)) begin : sram_keep_bot
			for (k=0; k<N_SRAM_OW; k=k+1) begin : keep_bit
`ifdef FORMAL
				// formal models the mux outputs as the only drivers
`elsif SIM
				assign spine_bot_sram_ow[k] = sram_sel_bot ? 1'bz : 1'b0;
`else
				gf180mcu_fd_sc_mcu7t5v0__bufz_1 keep_I (
					.I  (1'b0),
					.EN (~sram_sel_bot),
					.Z  (spine_bot_sram_ow[k])
				);
`endif
			end
		end else begin : sram_no_bot
			assign spine_bot_sram_ow = {N_SRAM_OW{1'b0}};
		end
	endgenerate

	assign {sram_cs, sram_we, sram_wmask, sram_addr, sram_wdata} = sram_ow;
	assign sram_we_lo = {`TT_SRAM_WMASK{sram_cs & sram_we & ~sram_addr[8]}} & sram_wmask;
	assign sram_we_hi = {`TT_SRAM_WMASK{sram_cs & sram_we &  sram_addr[8]}} & sram_wmask;

	// The Arrakeen compiler's 256x32 macro is banked twice to provide
	// a logical 512x32 SRAM. Delay the bank select with the synchronous data.
	always @(posedge pad_ui_in[0] or negedge pad_ui_in[1]) begin
		if (!pad_ui_in[1]) begin
			sram_bank_d <= 1'b0;
			sram_cs_d <= 1'b0;
			sram_we_lo_d <= {`TT_SRAM_WMASK{1'b0}};
			sram_we_hi_d <= {`TT_SRAM_WMASK{1'b0}};
			sram_wdata_d <= {`TT_SRAM_DATA{1'b0}};
		end else begin
			sram_bank_d <= sram_addr[8];
			sram_cs_d <= sram_cs;
			sram_we_lo_d <= sram_we_lo;
			sram_we_hi_d <= sram_we_hi;
			sram_wdata_d <= sram_wdata;
		end
	end

	// Read-data drive. The read bus reaches every SRAM branch (32 tiles over
	// several mm, ~4 pF per bit with four branches): left to synthesis it
	// was one buf_2 per bit and a dffrnq_1 bank select driving 32 muxes,
	// 40+ ns at 3.3V. So: a buffer on each select, a buf_16 per bit on the
	// trunk, and a buf_8 per bit per SRAM branch (below).
	wire sram_bank_b;
	wire sram_cs_b;
	wire [`TT_SRAM_DATA-1:0] sram_iw_pre;

`ifdef SIM
	assign sram_bank_b = sram_bank_d;
	assign sram_cs_b   = sram_cs_d;
	assign sram_iw     = sram_iw_pre;
`elsif FORMAL
	assign sram_bank_b = sram_bank_d;
	assign sram_cs_b   = sram_cs_d;
	assign sram_iw     = sram_iw_pre;
`else
	(* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_8 sram_bank_buf_I (.I (sram_bank_d), .Z (sram_bank_b));
	(* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_8 sram_cs_buf_I   (.I (sram_cs_d),   .Z (sram_cs_b));
	genvar q;
	generate
		for (q=0; q<`TT_SRAM_DATA; q=q+1) begin : sram_iw_buf
			(* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_16 buf_I (.I (sram_iw_pre[q]), .Z (sram_iw[q]));
		end
	endgenerate
`endif

	// Named so the bank-select output can carry an antenna diode (below).
	wire [`TT_SRAM_DATA-1:0] sram_q_sel = sram_bank_b ? sram_q_hi : sram_q_lo;

	assign sram_iw_pre = sram_cs_b ? sram_q_sel : {`TT_SRAM_DATA{1'b0}};

	// Antenna protection for the SRAM inputs. The macro uses thin-oxide
	// (3.3V) transistors and the foundry deck flagged the top-level wires
	// into d/we (ANT.16_i, Metal4/Metal5 ratio). A diode on each input net
	// discharges the wire during processing; it is a normal netlist cell,
	// so LVS checks it like any other.
`ifndef SIM
`ifndef FORMAL
	genvar d;
	generate
		for (d=0; d<`TT_SRAM_DATA; d=d+1) begin : sram_d_diode
			(* keep *) gf180mcu_fd_sc_mcu7t5v0__antenna ant_I (.I (sram_wdata_d[d]));
		end
		for (d=0; d<`TT_SRAM_WMASK; d=d+1) begin : sram_we_diode
			(* keep *) gf180mcu_fd_sc_mcu7t5v0__antenna ant_lo_I (.I (sram_we_lo_d[d]));
			(* keep *) gf180mcu_fd_sc_mcu7t5v0__antenna ant_hi_I (.I (sram_we_hi_d[d]));
		end
		for (d=0; d<8; d=d+1) begin : sram_a_diode
			(* keep *) gf180mcu_fd_sc_mcu7t5v0__antenna ant_I (.I (sram_addr[d]));
		end
		// Read path: the SRAM outputs and the bank-select result run a long
		// way to small 5V gates (ANT.16_ii, Metal3/Metal4 ratio).
		for (d=0; d<`TT_SRAM_DATA; d=d+1) begin : sram_q_diode
			(* keep *) gf180mcu_fd_sc_mcu7t5v0__antenna ant_lo_I  (.I (sram_q_lo[d]));
			(* keep *) gf180mcu_fd_sc_mcu7t5v0__antenna ant_hi_I  (.I (sram_q_hi[d]));
			(* keep *) gf180mcu_fd_sc_mcu7t5v0__antenna ant_sel_I (.I (sram_q_sel[d]));
			(* keep *) gf180mcu_fd_sc_mcu7t5v0__antenna ant_sel2_I (.I (sram_q_sel[d]));
		end
	endgenerate
`endif
`endif

	SP6TSRAM256x32 sram_lo_I (
		.a   (sram_addr[7:0]),
		.d   (sram_wdata_d),
		.we  (sram_we_lo_d),
		.clk (pad_ui_in[0]),
		.q   (sram_q_lo)
	);

	SP6TSRAM256x32 sram_hi_I (
		.a   (sram_addr[7:0]),
		.d   (sram_wdata_d),
		.we  (sram_we_hi_d),
		.clk (pad_ui_in[0]),
		.q   (sram_q_hi)
	);

	// Branches
	// --------

	genvar i, j;

	for (i=0; i<G_Y; i=i+1)
	begin : branch
		if (~MUX_MASK[i])
		begin : check_mask
			// Signals
			wire [S_OW-1:0] l_spine_ow;
			wire [S_IW-1:0] l_spine_iw;
			wire [N_SRAM_OW-1:0] l_sram_ow;

			wire [(U_OW*G_X)-1:0] l_um_ow;
			wire [(U_IW*G_X)-1:0] l_um_iw;
			wire [      G_X -1:0] l_um_ena;
			wire [      G_X -1:0] l_um_k_zero;
			wire [      G_X -1:0] l_um_pg_ena;

			wire [3:0] l_addr;
			wire       l_k_one;
			wire       l_k_zero;

			// Spine connection
			if (i & 1) begin
				assign spine_top_ow = l_spine_ow;
				assign l_spine_iw = spine_top_iw;
				if (SRAM_MASK[i])
					assign spine_top_sram_ow = l_sram_ow;
			end else begin
				assign spine_bot_ow = l_spine_ow;
				assign l_spine_iw = spine_bot_iw;
				if (SRAM_MASK[i])
					assign spine_bot_sram_ow = l_sram_ow;
			end

			// spine_iw = {gh, uio_in, ui_in, sel[8:0], ena, gl}: bit 1 is
			// si_ena and [10:7] is si_sel[8:5], which tt_mux compares with
			// its address straps (i >> 1).
			assign sram_branch_match[i] = SRAM_MASK[i] &&
				l_spine_iw[1] && (l_spine_iw[10:7] == (i >> 1));

			// The decode taps the spine select lines, which run the full
			// chip height into small 5V gates here (ANT.16_ii, Metal2).
			// A branch without SRAM support gets its sideband inputs tied
			// low (see below); an SRAM branch gets its own buf_8 per read bit
			// so each branch drives only its own run to its mux.
			wire [N_SRAM_IW-1:0] l_sram_iw;
			if (!SRAM_MASK[i]) begin : sram_iw_tie
				assign l_sram_iw = {N_SRAM_IW{1'b0}};
			end else begin : sram_iw_drv
`ifdef SIM
				assign l_sram_iw = sram_iw;
`elsif FORMAL
				assign l_sram_iw = sram_iw;
`else
				for (j=0; j<N_SRAM_IW; j=j+1) begin : b
					(* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_8 buf_I (.I (sram_iw[j]), .Z (l_sram_iw[j]));
				end
`endif
			end

`ifndef SIM
`ifndef FORMAL
			if (SRAM_MASK[i]) begin : sel_diode
				(* keep *) gf180mcu_fd_sc_mcu7t5v0__antenna ena_I (.I (l_spine_iw[1]));
				for (j=7; j<11; j=j+1) begin : sel
					(* keep *) gf180mcu_fd_sc_mcu7t5v0__antenna ant_I (.I (l_spine_iw[j]));
				end
			end

			// Each request bit is one spine net from every SRAM mux to the
			// SRAM front end: long Metal3/Metal4 runs into thick-gate inputs
			// (ANT.16_ii). One diode per bit per branch, next to that
			// branch's mux, protects each run. (The read data needs none:
			// each branch's run is driven by its own buf_8 above, whose
			// output diffusion protects it.)
			if (SRAM_MASK[i]) begin : sram_diode
				for (j=0; j<N_SRAM_OW; j=j+1) begin : ow
					(* keep *) gf180mcu_fd_sc_mcu7t5v0__antenna ant_I (.I (l_sram_ow[j]));
				end
			end
`endif
`endif

			// A branch without SRAM support gets its sideband inputs tied
			// low, so nothing floats and the shared read bus is not routed
			// to it. Constants (not the mux's l_k_zero) so synthesis gives
			// every input its own tie cell next to the pin: one l_k_zero net
			// strung along the 1.4mm mux edge to 32 inputs failed the
			// foundry antenna rule (ANT.16, thick-gate Metal3 ratio).

			// Branch Mux
			(* blackbox *)
			tt_mux
`ifdef SIM
			#(
				.N_UM (G_X),
				.N_I  (N_I),
				.N_O  (N_O),
				.N_IO (N_IO)
			)
`endif
			mux_I (
`ifdef USE_POWER_PINS
				.VDPWR     (VDPWR),
				.VGND      (VGND),
`endif
				.um_ow     (l_um_ow),
				.um_iw     (l_um_iw),
				.um_ena    (l_um_ena),
				.um_k_zero (l_um_k_zero),
				.um_pg_ena (l_um_pg_ena),
				.spine_ow  (l_spine_ow),
				.spine_iw  (l_spine_iw),
				.sram_ow   (l_sram_ow),
				.sram_iw   (l_sram_iw),
				.addr      (l_addr),
				.k_one     (l_k_one),
				.k_zero    (l_k_zero)
			);

			// Branch address tie-offs (constants, one tie cell each; see
			// l_sram_iw above for why not l_k_one/l_k_zero).
			for (j=0; j<4; j=j+1)
				if (i & (2<<j))
					assign l_addr[j] = 1'b1;
				else
					assign l_addr[j] = 1'b0;

			// Branch User modules
			for (j=0; j<G_X; j=j+1)
			begin : block
				tt_user_module #(
					.MUX_ID (i),
					.BLK_ID (j),
					.N_AE  (N_AE),
					.N_AU  (N_AU),
					.N_I   (N_I),
					.N_O   (N_O),
					.N_IO  (N_IO)
				) um_I (
`ifdef USE_POWER_PINS
					.VDPWR  (VDPWR),
					.VAPWR  (VAPWR),
					.VGND   (VGND),
`endif
					.ana    (pad_ana_analog),
					.ow     (l_um_ow[j*U_OW+:U_OW]),
					.iw     (l_um_iw[j*U_IW+:U_IW]),
					.ena    (l_um_ena[j]),
					.k_zero (l_um_k_zero[j]),
					.pg_ena (l_um_pg_ena[j])
				);
			end
		end
	end


	for (i=0; i<G_Y; i=i+1)
	begin : branch_match_mask
		if (MUX_MASK[i])
			assign sram_branch_match[i] = 1'b0;
	end


	// Logos
	// -----

`ifndef FORMAL
`ifndef SIM
`include "tt_logos.v"
`endif
`endif

endmodule // tt_top

`default_nettype wire
