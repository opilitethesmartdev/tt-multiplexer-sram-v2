// Minimal interfaces used only for the optional synthesis smoke test.
(* blackbox *) module tt_ctrl (
	input wire [7:0] pad_uio_in, input wire [9:0] pad_ui_in,
	output wire [7:0] pad_uio_out, pad_uio_oex, pad_uo_out,
	input wire [25:0] spine_top_ow, spine_bot_ow,
	output wire [29:0] spine_top_iw, spine_bot_iw,
	output wire sram_side_sel, input wire ctrl_sel_rst_n, ctrl_sel_inc, ctrl_ena,
	output wire k_one, k_zero
);
endmodule
(* blackbox *) module tt_mux (
	input wire [567:0] um_ow, output wire [399:0] um_iw,
	output wire [7:0] um_ena, um_k_zero, um_pg_ena,
	output wire [25:0] spine_ow, input wire [29:0] spine_iw,
	output wire [46:0] sram_ow, input wire [31:0] sram_iw,
	input wire [3:0] addr, output wire k_zero, k_one
);
endmodule
(* blackbox *) module tt_user_module #(
	parameter MUX_ID=0, BLK_ID=0, N_AE=12, N_AU=8, N_I=10, N_O=8, N_IO=8
)(
	inout wire [N_AE-1:0] ana, output wire [70:0] ow,
	input wire [49:0] iw, input wire ena, k_zero, pg_ena
);
endmodule
(* blackbox *) module SP6TSRAM256x32 (
	input wire [7:0] a, input wire [31:0] d, input wire [3:0] we,
	input wire clk, output wire [31:0] q
);
endmodule
