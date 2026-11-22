#
# Custom PDN configuration for tt_top / user_project_wrapper
#
# Copyright 2020-2022 Efabless Corporation
# Copyright 2023 Sylvain Munaut <tnt@246tNt.com>
# SPDX-License-Identifier: Apache-2.0
#

source $::env(SCRIPTS_DIR)/openroad/common/set_global_connections.tcl
set_global_connections

# Voltage nets
set secondary []
foreach vdd $::env(VDD_NETS) gnd $::env(GND_NETS) {
    if { $vdd != $::env(VDD_NET)} {
        lappend secondary $vdd

        set db_net [[ord::get_db_block] findNet $vdd]
        if {$db_net == "NULL"} {
            set net [odb::dbNet_create [ord::get_db_block] $vdd]
            $net setSpecial
            $net setSigType "POWER"
        }
    }

    if { $gnd != $::env(GND_NET)} {
        lappend secondary $gnd

        set db_net [[ord::get_db_block] findNet $gnd]
        if {$db_net == "NULL"} {
            set net [odb::dbNet_create [ord::get_db_block] $gnd]
            $net setSpecial
            $net setSigType "GROUND"
        }
    }
}

set_voltage_domain -name CORE -power $::env(VDD_NET) -ground $::env(GND_NET) \
    -secondary_power $secondary

# Met5 horizontal stripes.
#
# There is deliberately no vertical Metal4 stripe here. Each branch row holds
# two muxes side by side that span almost the whole core width (86.8..3079.5),
# so a Metal4 strap is snipped into fragments at every branch row and cannot
# tie anything together. The macro power pins are on Metal4 and connect up to
# these Metal5 stripes through the macro grid below.
define_pdn_grid \
    -name stdcell_grid \
    -starts_with POWER \
    -voltage_domain CORE

add_pdn_stripe \
    -grid stdcell_grid \
    -layer $::env(FP_PDN_HORIZONTAL_LAYER) \
    -width $::env(FP_PDN_HWIDTH) \
    -pitch $::env(FP_PDN_HPITCH) \
    -offset $::env(FP_PDN_HOFFSET) \
    -spacing $::env(FP_PDN_HSPACING) \
    -starts_with POWER -extend_to_core_ring

add_pdn_connect \
    -grid stdcell_grid \
    -layers "$::env(FP_PDN_VERTICAL_LAYER) $::env(FP_PDN_HORIZONTAL_LAYER)"

# Add the core ring
# `-connect_to_pads` ties the ring to the wrapper's power pins. Those pins sit
# on Metal3 at the die edge, while the ring is on Metal4/Metal5 and is snipped
# at exactly the pin locations, so without this the grid has no supply source
# at all and PDNSim reports the whole net as unconnected.
add_pdn_ring \
    -grid stdcell_grid \
    -layers "$::env(FP_PDN_VERTICAL_LAYER) $::env(FP_PDN_HORIZONTAL_LAYER)" \
    -widths "$::env(FP_PDN_CORE_RING_VWIDTH) $::env(FP_PDN_CORE_RING_HWIDTH)" \
    -spacings "$::env(FP_PDN_CORE_RING_VSPACING) $::env(FP_PDN_CORE_RING_HSPACING)" \
    -core_offset "$::env(FP_PDN_CORE_RING_VOFFSET) $::env(FP_PDN_CORE_RING_HOFFSET)" \
    -connect_to_pads -connect_to_pad_layers Metal3

# Macro connections
#
# Deliberately none here. pdngen connects a macro pin to the Metal5 stripes by
# dropping a generate-rule via array sized from the pin, and these macros'
# power pins are up to 17um wide strips, so it produced 17.7 x 3.1um Via4
# arrays on Metal4. That geometry is special/fixed, i.e. invisible to
# TritonRoute, which then ran the module's signal nets straight through them
# (11 Metal4.Short violations between uio_oe[0] and vgnd).
#
# Macro power pins are connected in TT.Top.CustomRoute instead
# (MacroPowerVias: single-cut Via4s inside the pin, plus a short Metal4 jog for
# pins that fall between two stripes), which the router can route around.

# The Arrakeen SRAM's vdd/vss pins are Metal3 strips that interleave every
# 0.5-27um, so a Metal4 strap over the macro (what this grid used to draw)
# touches both supplies and shorts them. They are connected per strip in
# TT.Top.CustomRoute instead (MacroPowerVias: Via3 -> short Metal4 jog ->
# Via4 on the matching Metal5 stripe), which cannot cross the other supply.
