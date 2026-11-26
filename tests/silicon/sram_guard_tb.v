`timescale 1ns/1ps
`default_nettype none
`include "tt_defs.vh"

// Only the top-level guard and real SRAM model are under test. Spine buses
// are forced to emulate selected/unselected hardened tt_mux macros.
module tt_ctrl (
	input wire [7:0] pad_uio_in, input wire [9:0] pad_ui_in,
	output wire [7:0] pad_uio_out, pad_uio_oex, pad_uo_out,
	input wire [25:0] spine_top_ow, spine_bot_ow,
	output wire [29:0] spine_top_iw, spine_bot_iw,
	output wire sram_side_sel, input wire ctrl_sel_rst_n, ctrl_sel_inc, ctrl_ena,
	output wire k_one, k_zero
);
	assign k_one = 1'b1;
	assign k_zero = 1'b0;
endmodule

module tt_mux (
	input wire [567:0] um_ow, output wire [399:0] um_iw,
	output wire [7:0] um_ena, um_k_zero, um_pg_ena,
	output wire [25:0] spine_ow, input wire [29:0] spine_iw,
	output wire [46:0] sram_ow, input wire [31:0] sram_iw,
	input wire [3:0] addr, output wire k_zero, k_one
);
	assign k_zero = 1'b0;
	assign k_one = 1'b1;
	assign spine_ow = 26'bz;
	assign sram_ow = 47'bz;
endmodule

module tt_user_module #(
	parameter MUX_ID=0, BLK_ID=0, N_AE=12, N_AU=8, N_I=10, N_O=8, N_IO=8
)(
	inout wire [N_AE-1:0] ana, output wire [70:0] ow,
	input wire [49:0] iw, input wire ena, k_zero, pg_ena
);
	assign ow = 71'b0;
endmodule

module sram_guard_tb;
	reg [43:0] inputs = 0;
	wire [43:0] outputs, enables;
	wire [43:0] analog_pins;
	wire zero, one;
	reg [29:0] top_spine = 0, bot_spine = 0;
	reg side = 1;
	reg [46:0] request = 0;
	integer branch;
	tt_top dut (.io_ana(analog_pins), .io_in(inputs), .io_out(outputs),
		.io_oex(enables), .k_zero(zero), .k_one(one));

	task tick;
		begin
			inputs[14] = 0; #5;
			inputs[14] = 1; #5;
			inputs[14] = 0; #1;
		end
	endtask

	initial begin
		force dut.spine_top_iw = top_spine;
		force dut.spine_bot_iw = bot_spine;
		force dut.sram_side_sel = side;
		force dut.spine_top_sram_ow = request;
		force dut.spine_bot_sram_ow = 47'bz;
		inputs[38] = 1; // ctrl_ena
		request = 47'h7fffffffffff;
		top_spine[1] = 1;
		for (branch = 0; branch < 8; branch = branch + 1) begin
			top_spine[10:7] = branch;
			#1;
			if ((branch == 2 || branch == 3 || branch == 5 || branch == 7)) begin
				if (dut.sram_ow !== request)
					$fatal(1, "supported branch %0d not enabled", 2*branch+1);
			end else if (dut.sram_ow !== 47'b0)
				$fatal(1, "unsupported branch %0d did not isolate SRAM", 2*branch+1);
		end
		// The actual disconnected spine is high impedance, not a zero bus.
		top_spine[10:7] = 0;
		request = 47'bz;
		#1;
		if (dut.sram_ow !== 47'b0)
			$fatal(1, "floating unsupported spine reached SRAM");
		request = 47'h7fffffffffff;
		top_spine[1] = 0;
		#1;
		if (dut.sram_ow !== 47'b0)
			$fatal(1, "disabled side did not isolate SRAM");
		inputs[38] = 0;
		top_spine[1] = 1;
		top_spine[10:7] = 2;
		#1;
		if (dut.sram_ow !== 47'b0)
			$fatal(1, "disabled controller did not isolate SRAM");
		// A short functional smoke test of both banks and byte writes. This
		// checks the behavioral model only, not physical SRAM timing or LVS.
		inputs[15] = 0; #1;
		tick();
		inputs[15] = 1;
		inputs[38] = 1;
		request = {1'b1, 1'b1, 4'hf, 9'h001, 32'h12345678};
		tick();
		request = 0;
		tick();
		request = {1'b1, 1'b1, 4'hf, 9'h101, 32'hdeadbeef};
		tick();
		request = 0;
		tick();
		request = {1'b1, 1'b1, 4'h5, 9'h001, 32'haabbccdd};
		tick();
		request = 0;
		tick();
		request = {1'b1, 1'b0, 4'h0, 9'h001, 32'b0};
		tick();
		if (dut.sram_iw !== 32'h12bb56dd)
			$fatal(1, "low bank / byte mask mismatch: %h", dut.sram_iw);
		request = {1'b1, 1'b0, 4'h0, 9'h101, 32'b0};
		tick();
		if (dut.sram_iw !== 32'hdeadbeef)
			$fatal(1, "high bank mismatch: %h", dut.sram_iw);
		$display("PASS SRAM branch guard, banks and byte masks");
		$finish;
	end
endmodule
