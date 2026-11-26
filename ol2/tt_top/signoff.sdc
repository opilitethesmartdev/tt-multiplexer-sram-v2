#
# TT top level STA
#


# Segment signals
# ---------------

# Port: Control inputs
set all_ctl [list]
for {set i 0} {$i < 6} {incr i} {
	set j [expr $i+38]
	lappend all_ctl [ get_ports "gpio_in[$j]" ]
}

# Port: User IO
set all_pads_in  [list]
set all_pads_out [list]

	# UIO
for {set i 0} {$i < 8} {incr i} {
	set j [expr $i+16]
	lappend all_pads_in  [ get_ports "gpio_in[$j]" ]
	lappend all_pads_out [ get_ports "gpio_out[$j]" ]
	lappend all_pads_out [ get_ports "gpio_oeb[$j]" ]
}

	# UO
for {set i 0} {$i < 8} {incr i} {
	set j [expr $i+24]
	lappend all_pads_out [ get_ports "gpio_out[$j]" ]
}

	# UI
for {set i 0} {$i < 7} {incr i} {
	set j [expr $i+0]
	lappend all_pads_in  [ get_ports "gpio_in[$j]" ]
}
for {set i 0} {$i < 3} {incr i} {
	set j [expr $i+13]
	lappend all_pads_in  [ get_ports "gpio_in[$j]" ]
}

# Pins: User modules
set all_pins_um_ctl [ get_pins "*.tt_um_I/buf_ctl*/A" ]
set all_pins_um_iw  [ get_pins "*.tt_um_I/buf_in*/A" ]
set all_pins_um_ow  [ get_pins "*.tt_um_I/buf_out*/X" ]


# Inputs
# ------

# All `io_in` come from strong buffer in the gpio_control_block.
# The driving cell is PDK specific: the SKY130 library uses `buf_16` with
# `A`/`X` pins, GF180MCU uses `buf_8` with `I`/`Z` pins. Try each in turn
# rather than keying off the PDK name, so this stays valid for any library.
if {[catch {
	set_driving_cell -lib_cell gf180mcu_fd_sc_mcu7t5v0__buf_8 -pin Z [all_inputs]
} _drv_err]} {
	set_driving_cell -lib_cell sky130_fd_sc_hd__buf_16 -pin X [all_inputs]
}


# Loads
# -----

# All `io_out` & `io_oex` go to gpio_control_block and have a bit
# of capacitance (estimates from lib and gpio_control_block.spef)
set_load 0.03 [all_outputs]


# Assumptions
# -----------

# We assume the pull are disabled since it messes with the analysis
# (STA can't "see" that those are only active when disabled)
set_case_analysis one [get_pins *.mux_I/*bus_pull_ow_I*/TE_B]
set_case_analysis one [get_pins *.ctrl_I/*tbuf_spine_ow_I*/TE_B]


# Clock
# -----

# The GF180 wrapper exposes raw pads, unlike the original GPIO wrapper.
# A missing port must not silently create an unconnected virtual clock.
# The user clock period here is an analysis assumption, not a supported
# frequency: SRAM macro timing models and complete I/O constraints are still
# required before this can be used as silicon timing sign-off.
set gf_ctrl_clk [get_ports -quiet {pad_raw[1]}]
set gf_user_clk [get_ports -quiet {pad_raw[55]}]
if {[llength $gf_ctrl_clk] > 0} {
	if {[llength $gf_user_clk] == 0} {
		error {GF180 user clock pad_raw[55] is missing}
	}
	create_clock -name ctrl_inc -period 10 $gf_ctrl_clk
	create_clock -name user_clk -period 100 $gf_user_clk
} else {
	create_clock -name ctrl_inc -period 10 [get_ports {gpio_in[39]}]
}


# Max delays
# ----------

# No artifical delays
set_input_delay  0 [all_inputs]
set_output_delay 0 [all_outputs]

# Drop objects that do not exist. On GF180MCU the wrapper exposes
# `pad_raw[]` instead of the SKY130 `gpio_in[]`/`gpio_out[]` ports, and a
# `get_ports`/`get_pins` that matches nothing still yields an empty element
# for every `lappend`, so these lists are non-empty but contain only empty
# strings. OpenSTA aborts the whole SDC when `group_path` receives them.
proc tt_objects {objs} {
	set out [list]
	foreach o $objs {
		if {[string length $o] > 0} {
			lappend out $o
		}
	}
	return $out
}

# Apply a path group + max delay, skipping it when either end is empty.
proc tt_group_path {name frm to delay} {
	set from [tt_objects $frm]
	set to   [tt_objects $to]
	if {[llength $from] == 0 || [llength $to] == 0} {
		return
	}
	group_path    -from $from -to $to -name $name
	set_max_delay -from $from -to $to $delay
}

# Control delays
tt_group_path ctl_to_ctl     $all_ctl        $all_pins_um_ctl 15.0
tt_group_path ctl_to_inward  $all_ctl        $all_pins_um_iw  15.0
tt_group_path ctl_to_outward $all_ctl        $all_pads_out    30.0

# User IO
tt_group_path io_inward      $all_pads_in    $all_pins_um_iw   5.0
tt_group_path io_outward     $all_pins_um_ow $all_pads_out    12.5
