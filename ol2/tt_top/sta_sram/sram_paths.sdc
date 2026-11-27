# GF180 timing constraints for the shared-SRAM interface.
# The user clock is pad_raw[55] (u_clk); the SRAM, its front-end flops and
# every tile are clocked from it. Clocks propagated through the real
# clock path: pad -> tt_top -> spine -> tt_mux -> tile.
create_clock -name uclk -period $::env(UCLK_PERIOD) [get_ports {pad_raw[55]}]
set_propagated_clock [all_clocks]
set_clock_uncertainty 0.25 [all_clocks]
set_case_analysis one [get_pins -quiet -hierarchical *bus_pull_ow_I*/TE_B]
set_case_analysis one [get_pins -quiet -hierarchical *tbuf_spine_ow_I*/TE_B]
