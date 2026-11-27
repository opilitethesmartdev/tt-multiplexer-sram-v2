# 3.3 V timing of the shared-SRAM interface

`signoff.sdc` was written for Sky130: on GF180 its `gpio_in[]` ports do not
exist, so the tt_top sign-off STA has no clock and checks no path. This
directory times the SRAM interface on its own, at the chip's real 3.3 V
supply (tt_top's flow uses the 5 V corners).

* `sram_paths.sdc` — user clock on `pad_raw[55]`, propagated through the real
  clock tree (pad → tt_top → spine → tt_mux → tile).
* `SP6TSRAM256x32_ideal.lib` — the Arrakeen SRAM has no timing model; this
  placeholder has zero setup/hold/clk→q, so slack against it is the window
  the real macro must fit in.
* `mkstubs.py` — blackbox stubs for macros without timing views.
* `sta.tcl` — loads std-cell liberty for one 3.3 V corner, the SRAM tile's
  liberty, the tt_mux/tt_ctrl netlists and SPEFs, and reports every endpoint.
* `summarize.py` — groups the endpoints (tile ← read data, SRAM pins,
  front-end flops) with worst slack per group.

It needs a tt_top build that contains SRAM tiles (the real config has none
yet): one `tt_um_example_sram` from hexa3/ttgf-sram-template per SRAM
branch was used. Env: `PDK_ROOT`, `TILE_LIB_DIR` (the tile's `final/lib`), `TREE`, `RUN`, `CORNER` (`ss_125C_3v00`,
`tt_025C_3v30`, `ff_n40C_3v60`), `RC` (`max`/`nom`/`min`), `UCLK_PERIOD`.

Result (4 SRAM tiles, period 20 ns):

| Corner | Request setup | Read-data setup | Read-data hold |
|---|---|---|---|
| ss 125 °C 3.0 V | −16.8 ns | +4.4 ns | +0.08 ns |
| tt 25 °C 3.3 V | +1.5 ns | +12.2 ns | −0.01 ns |
| ff −40 °C 3.6 V | +9.2 ns | +15.4 ns | −0.09 ns |

So the interface runs at ~50 MHz typical and ~25 MHz worst case (request:
≈8 ns clock skew tile-vs-SRAM + ≈10.5 ns through tt_mux + spine). The hold
numbers are against a zero clk→q SRAM: any real access time > 0.1 ns covers
them. The SRAM's own address setup and read access time come on top.

Run (inside the Nix shell):

```sh
cd ol2/tt_top/sta_sram
python3 mkstubs.py ../verilog stubs.v
PDK_ROOT=... TILE_LIB_DIR=.../final/lib TREE=../../.. RUN=../runs/RUN_x \
  CORNER=ss_125C_3v00 RC=max UCLK_PERIOD=20 sta -no_splash -exit sta.tcl > ss.log
python3 summarize.py ss.log
```
