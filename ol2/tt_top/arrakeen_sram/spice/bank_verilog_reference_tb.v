// Check that bank_functional.spice expected words match the compiler's
// behavioral model. This is NOT a substitute for the transistor simulation.
`timescale 1ns/1ps
`default_nettype none
module bank_verilog_reference_tb;
	reg clk = 0;
	reg [7:0] a = 0;
	reg [3:0] we = 0;
	reg [31:0] d = 0;
	wire [31:0] q;
	SP6TSRAM256x32 dut(.clk(clk), .a(a), .we(we), .d(d), .q(q));

	task cycle(input [7:0] addr, input [3:0] mask, input [31:0] data);
		begin
			a = addr; we = mask; d = data;
			#50 clk = 1;
			#90 clk = 0;
			#60;
		end
	endtask
	initial begin
		cycle(0,   0, 32'h0);
		cycle(255, 15, 32'haa55aa55);
		cycle(0,   15, 32'h55aa55aa);
		cycle(255, 5, 32'h12345678);
		cycle(0,   0, 32'h0);
		if (q !== 32'haa34aa78) $fatal(1, "s0 %h", q);
		cycle(255, 0, 32'h0);
		if (q !== 32'h55aa55aa) $fatal(1, "s1 %h", q);
		cycle(0,   0, 32'h0);
		if (q !== 32'haa34aa78) $fatal(1, "s2 %h", q);
		$display("PASS behavioral reference expectations");

		// Mirror bank_write_address.spice: initialize both locations,
		// then change the address at the write edge.
		cycle(0,   0, 0);
		cycle(0,   15, 0);
		cycle(255, 0, 0);
		cycle(255, 15, 0);
		cycle(0,   0, 0);
		cycle(255, 15, 32'haa55aa55);
		cycle(0,   0, 0);
		if (q !== 32'haa55aa55) $fatal(1, "write-address s0 %h", q);
		cycle(255, 0, 0);
		if (q !== 32'h0) $fatal(1, "write-address s1 %h", q);
		$display("PASS behavioral write-address expectations");
		$finish;
	end
endmodule
`default_nettype wire
