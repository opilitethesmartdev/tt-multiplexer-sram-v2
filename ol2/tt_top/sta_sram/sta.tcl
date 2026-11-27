set here [file dirname [file normalize [info script]]]
# Timing of the shared-SRAM interface at the real 3.3 V supply.
# env: TREE (mux tree), RUN (run dir), CORNER (tt_025C_3v30 / ss_125C_3v00 / ff_n40C_3v60),
#      RC (nom/min/max), UCLK_PERIOD (ns)
set pdk $::env(PDK_ROOT)/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib
set c $::env(CORNER)
set tt $::env(TREE)/ol2/tt_top
read_liberty $pdk/gf180mcu_fd_sc_mcu7t5v0__${c}.lib
foreach f [glob -nocomplain $::env(TILE_LIB_DIR)/nom_${c}/*.lib] { read_liberty $f }
read_liberty $here/SP6TSRAM256x32_ideal.lib
read_verilog $tt/verilog/tt_mux.nl.v
read_verilog $tt/verilog/tt_ctrl.nl.v
read_verilog $here/stubs.v
read_verilog $::env(RUN)/final/nl/tt_gf_wrapper.nl.v
link_design tt_gf_wrapper
read_spef $::env(RUN)/final/spef/$::env(RC)/tt_gf_wrapper.$::env(RC).spef
foreach i [get_cells *] {
	set r [get_property $i ref_name]
	if {$r == "tt_mux" || $r == "tt_ctrl"} {
		read_spef -path [get_full_name $i] $tt/spef/$r.$::env(RC).spef
	}
}
source $here/sram_paths.sdc
puts "=== CORNER $c RC $::env(RC) period $::env(UCLK_PERIOD)"
puts "=== clock latency"
catch {report_clock_latency -include_internal_latency}
catch {report_clock_skew}
puts "=== setup"
report_checks -path_delay max -group_path_count 8 -endpoint_path_count 1 -format end
report_checks -path_delay max -fields {slew cap fanout} -digits 3
puts "=== hold"
report_checks -path_delay min -group_path_count 8 -endpoint_path_count 1 -format end
report_checks -path_delay min -digits 3
puts "=== ALLEND max"
report_checks -path_delay max -group_path_count 5000 -endpoint_path_count 1 -format end
puts "=== ALLEND min"
report_checks -path_delay min -group_path_count 5000 -endpoint_path_count 1 -format end
report_tns
report_wns
report_worst_slack -max
report_worst_slack -min
