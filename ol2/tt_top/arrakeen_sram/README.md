# Arrakeen 512x32 shared SRAM

This project generates the GF180MCU physical views for the shared SRAM used by the TinyTapeout multiplexer.

The logical memory is **512 words × 32 bits** with four byte write enables. The current Arrakeen compiler cannot place a monolithic 512×32 macro, so the implementation uses two identical **256×32** macros:

- `SP6TSRAM256x32` bank 0 stores addresses 0–255
- `SP6TSRAM256x32` bank 1 stores addresses 256–511
- Address bit 8 selects the bank; bits 7:0 address the selected macro
- Both banks share the 32-bit data bus, four byte write enables, and clock

Run the generator from `ol2/tt_top` with:

```powershell
uv sync --project arrakeen_sram
uv run --project arrakeen_sram arrakeen_sram/generate_views.py
```

The generated GDS, LEF, and Verilog views are written to the parent `gds/`, `lef/`, and `verilog/` directories.

## Interface timing

The shared interface is synchronous to `pad_ui_in[0]`:

- `sram_cs`, `sram_we`, `sram_wmask`, `sram_addr`, and `sram_wdata` are sampled on the rising edge
- Read data is returned one cycle later on `sram_rdata`
- The Arrakeen macro has a registered address input, so the wrapper delays write enables and write data by one cycle; a write request is committed on the following edge
- The wrapper captures the bank select with the read request, so the returned data comes from the correct 256-word bank
- Keep the requesting module selected until its read response is consumed
