`timescale 1ns/1ps
`default_nettype none

// Exercise the actual wrapper, with the GF180 cell model supplied separately.
module tt_top (
	input wire [43:0] io_in,
	inout wire [43:0] io_ana,
	output wire [43:0] io_out, io_oex,
	output wire k_zero, k_one
);
	reg [7:0] oe, data;
	assign io_out = {12'b0, 8'h69, data, 16'b0};
	assign io_oex = {12'b0, 8'hff, oe, 16'b0};
	assign k_zero = 0;
	assign k_one = 1;
endmodule

module uio_tb;
	wire [73:0] pads;
	reg [7:0] external_data, external_enable;
	genvar i;
	generate for (i=0; i<8; i=i+1) begin
		assign pads[37+i] = external_enable[i] ? external_data[i] : 1'bz;
	end endgenerate
	tt_gf_wrapper dut (.pad_raw(pads));

	initial begin
		dut.top_I.oe = 8'h00;
		dut.top_I.data = 8'hff;
		external_enable = 8'hff;
		external_data = 8'h35;
		#1;
		if (pads[44:37] !== 8'h35 || dut.top_I.io_in[23:16] !== 8'h35)
			$fatal(1, "input mode must not drive or corrupt any bit");
		dut.top_I.oe = 8'ha5;
		dut.top_I.data = 8'hc3;
		external_enable = ~8'ha5;
		external_data = 8'h5a;
		#1;
		if (pads[44:37] !== ((8'hc3 & 8'ha5) | (8'h5a & ~8'ha5)))
			$fatal(1, "mixed input/output enables must work per bit");
		if (pads[16:9] !== 8'h69)
			$fatal(1, "dedicated outputs are incorrect");
		dut.top_I.oe = 8'h00;
		external_enable = 8'h00;
		#1;
		if (pads[44:37] !== 8'hzz)
			$fatal(1, "disabled uio bits must be high impedance");
		$display("PASS uio per-bit enable");
		$finish;
	end
endmodule
