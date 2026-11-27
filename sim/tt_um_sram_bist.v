/*
 * tt_um_sram_bist.v
 *
 * Self-checking test tile for the shared Arrakeen SRAM (simulation only).
 *
 * Runs through the full user-module -> mux -> spine -> tt_top -> SRAM path:
 *
 *   1. write every word (0..511, so both 256-word banks) with a full-width
 *      pattern that toggles every data bit across the address space
 *   2. rewrite bytes 0 and 2 of every word (wmask 4'b0101) with the inverse,
 *      so the byte enables are checked to write only the selected bytes
 *   3. read every word back, one read per cycle (pipelined: the data for a
 *      read issued in cycle N arrives in cycle N+1), and OR the difference
 *      against the expected value into err_bits
 *
 * uo_out[0] = done, uo_out[1] = pass (done and no bit ever wrong),
 * uo_out[2] = any error, uo_out[7:3] = low bits of the error bitmap.
 * The full 32-bit error bitmap is err_bits (read hierarchically by the TB).
 *
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module tt_um_sram_bist (
`ifdef USE_POWER_PINS
	input  wire VDPWR,
	input  wire VAPWR,
	input  wire VGND,
`endif
	input  wire [7:0] ui_in,
	output wire [7:0] uo_out,
	input  wire [7:0] uio_in,
	output wire [7:0] uio_out,
	output wire [7:0] uio_oe,
	input  wire       ena,
	input  wire       clk,
	input  wire       rst_n,
	output reg        sram_cs,
	output reg        sram_we,
	output reg  [3:0] sram_wmask,
	output reg  [8:0] sram_addr,
	output reg [31:0] sram_wdata,
	input  wire [31:0] sram_rdata
);

	localparam [1:0] S_FILL = 2'd0, S_BYTE = 2'd1, S_READ = 2'd2, S_DONE = 2'd3;

	// Every data bit takes both values within each 256-word bank (each byte
	// is derived from a[7:0]), and a[8] inverts the whole word so a bank
	// mix-up (lo/hi data swapped) can never read back as correct.
	function [31:0] pat(input [8:0] a);
		pat = {a[7:0], a[7:0] ^ 8'h5a, ~a[7:0], a[7:0] ^ 8'ha5} ^ {32{a[8]}};
	endfunction

	function [31:0] exp_word(input [8:0] a);
		reg [31:0] p;
		begin
			p = pat(a);
			exp_word = {p[31:24], ~p[23:16], p[15:8], ~p[7:0]};
		end
	endfunction

	reg [1:0]  state;
	reg [9:0]  idx;          // one extra bit to finish the read pipeline
	reg        rd_valid;
	reg [8:0]  rd_addr;
	reg [31:0] err_bits;
	reg [9:0]  n_checked;

	assign uo_out  = { err_bits[4:0], |err_bits, (state == S_DONE) & ~|err_bits
		& (n_checked == 10'd512), state == S_DONE };
	assign uio_out = 8'h00;
	assign uio_oe  = 8'h00;

	always @(posedge clk or negedge rst_n)
		if (~rst_n) begin
			state      <= S_FILL;
			idx        <= 0;
			sram_cs    <= 1'b0;
			sram_we    <= 1'b0;
			sram_wmask <= 4'h0;
			sram_addr  <= 9'd0;
			sram_wdata <= 32'd0;
			rd_valid   <= 1'b0;
			rd_addr    <= 9'd0;
			err_bits   <= 32'd0;
			n_checked  <= 0;
		end else begin
			// Check the read issued in the previous cycle.
			if (rd_valid) begin
				err_bits  <= err_bits | (sram_rdata ^ exp_word(rd_addr));
				n_checked <= n_checked + 1;
			end
			rd_valid <= 1'b0;

			case (state)
			S_FILL: begin
				sram_cs    <= 1'b1;
				sram_we    <= 1'b1;
				sram_wmask <= 4'hf;
				sram_addr  <= idx[8:0];
				sram_wdata <= pat(idx[8:0]);
				idx        <= idx + 1;
				if (idx == 10'd511) begin
					state <= S_BYTE;
					idx   <= 0;
				end
			end
			S_BYTE: begin
				sram_cs    <= 1'b1;
				sram_we    <= 1'b1;
				sram_wmask <= 4'b0101;
				sram_addr  <= idx[8:0];
				sram_wdata <= ~pat(idx[8:0]);
				idx        <= idx + 1;
				if (idx == 10'd511) begin
					state <= S_READ;
					idx   <= 0;
				end
			end
			S_READ: begin
				if (idx < 10'd512) begin
					sram_cs    <= 1'b1;
					sram_we    <= 1'b0;
					sram_wmask <= 4'h0;
					sram_addr  <= idx[8:0];
					sram_wdata <= 32'd0;
					idx        <= idx + 1;
				end else begin
					sram_cs <= 1'b0;
					state   <= S_DONE;
				end
				// The request presented now is sampled by the SRAM at the next
				// edge; its data is on sram_rdata during the cycle after that.
				rd_valid <= sram_cs & ~sram_we & (state == S_READ);
				rd_addr  <= sram_addr;
			end
			S_DONE: begin
				sram_cs <= 1'b0;
				sram_we <= 1'b0;
			end
			endcase
		end

endmodule

`default_nettype wire
