module SP6TSRAM256x32(a, d, we, clk, q);
  input wire [7:0] a;
  input wire [31:0] d;
  input wire [3:0] we;
  input wire clk;
  output wire [31:0] q;

  reg [31:0] mem [0:255];
  reg [7:0] a_latch;

  always @(posedge clk) begin
    a_latch <= a;
    if (we[0]) begin
      mem[a_latch][7:0] <= d[7:0];
    end
    if (we[1]) begin
      mem[a_latch][15:8] <= d[15:8];
    end
    if (we[2]) begin
      mem[a_latch][23:16] <= d[23:16];
    end
    if (we[3]) begin
      mem[a_latch][31:24] <= d[31:24];
    end
  end

  assign q = mem[a_latch];
endmodule
