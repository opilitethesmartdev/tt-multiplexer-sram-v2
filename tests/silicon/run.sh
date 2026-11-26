#!/bin/sh
# Run from any directory; requires Python 3, Icarus Verilog and vvp.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
cd "$root"
python3 tests/silicon/test_uio_netlist_check.py
iverilog -g2012 -DFUNCTIONAL -s uio_tb -I tests/silicon \
	-o "$tmp/uio" sim/gf180mcuD/gf180mcu_fd_sc_mcu7t5v0.v \
	ol2/tt_top/tt_gf_wrapper.v tests/silicon/uio_tb.v
vvp "$tmp/uio"
iverilog -g2012 -DFORMAL -s sram_guard_tb -I tests/silicon \
	-o "$tmp/sram" rtl/tt_top.v rtl/SP6TSRAM256x32.v \
	tests/silicon/sram_guard_tb.v
vvp "$tmp/sram"
