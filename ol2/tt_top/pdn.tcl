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

# Met5 horizontal stripes and the matching Metal4 vertical straps. Both are
# needed: the horizontal stripes alone are only tied together by the core
# ring, and the ring gets snipped wherever a macro power pin of the opposite
# net sits on it, leaving whole stripes unconnected (PDNSim PSM-0069).
define_pdn_grid \
    -name stdcell_grid \
    -starts_with POWER \
    -voltage_domain CORE

add_pdn_stripe \
    -grid stdcell_grid \
    -layer $::env(FP_PDN_VERTICAL_LAYER) \
    -width $::env(FP_PDN_VWIDTH) \
    -pitch $::env(FP_PDN_VPITCH) \
    -offset $::env(FP_PDN_VOFFSET) \
    -spacing $::env(FP_PDN_VSPACING) \
    -starts_with POWER -extend_to_core_ring

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
add_pdn_ring \
    -grid stdcell_grid \
    -layers "$::env(FP_PDN_VERTICAL_LAYER) $::env(FP_PDN_HORIZONTAL_LAYER)" \
    -widths "$::env(FP_PDN_CORE_RING_VWIDTH) $::env(FP_PDN_CORE_RING_HWIDTH)" \
    -spacings "$::env(FP_PDN_CORE_RING_VSPACING) $::env(FP_PDN_CORE_RING_HSPACING)" \
    -core_offset "$::env(FP_PDN_CORE_RING_VOFFSET) $::env(FP_PDN_CORE_RING_HOFFSET)"

# Macro connections
define_pdn_grid \
    -macro \
    -name macro \
    -cells "^(tt_(ctrl|mux|pg|um|asw)(_.*)?)$" \
    -starts_with POWER \
    -halo "$::env(FP_PDN_HORIZONTAL_HALO) $::env(FP_PDN_VERTICAL_HALO)"

add_pdn_connect \
    -grid macro \
    -layers "$::env(FP_PDN_VERTICAL_LAYER) $::env(FP_PDN_HORIZONTAL_LAYER)"

# Arrakeen SRAM macros expose their vdd/vss pins on Metal3, so add an
# explicit Metal4 -> Metal3 connection and Metal4 straps over the macros
# to tie them into the Metal4/Metal5 grid.
define_pdn_grid \
    -macro \
    -name sram_macros \
    -cells "SP6TSRAM256x32" \
    -starts_with POWER \
    -halo "$::env(FP_PDN_HORIZONTAL_HALO) $::env(FP_PDN_VERTICAL_HALO)"

add_pdn_connect \
    -grid sram_macros \
    -layers "$::env(FP_PDN_VERTICAL_LAYER) $::env(FP_PDN_HORIZONTAL_LAYER)"

add_pdn_connect \
    -grid sram_macros \
    -layers "$::env(FP_PDN_VERTICAL_LAYER) Metal3"

# The straps must land on the vdd/vss strips, which start at x=35.65um inside
# the macro, and must stay clear of the a[] pins that run along the left edge
# (x 0..2.98um). An offset of 0.68 put a Metal4 strap right on top of those
# pins: signal vias from the pins shorted into it (DRT reported
# "Short net:_105_ net:vdpwr" on Metal4 at the macro edge).
add_pdn_stripe \
    -grid sram_macros \
    -layer Metal4 \
    -width 1.36 \
    -offset 40 \
    -spacing 0.28 \
    -pitch 284.16 \
    -starts_with POWER \
    -number_of_straps 2
