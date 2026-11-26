# Candidate raw Magic GDS extraction. Source this inside a Magic session
# initialized with the matching gf180mcuD PDK .magicrc.
#
# Required environment:
#   FULL_GDS_INPUT   absolute path of the *exact* selected GDS
#   FULL_GDS_TOP     top cell name (for this shuttle: tt_gf_wrapper)
#   FULL_GDS_OUTDIR  new, empty output directory
#
# This deliberately performs no MergeWellNets/DEF connectivity repair.
# It is not a complete simulation deck, PEX, or proof of LVS.
foreach var {FULL_GDS_INPUT FULL_GDS_TOP FULL_GDS_OUTDIR} {
    if {![info exists ::env($var)] || $::env($var) eq ""} {
        error "Set environment variable $var"
    }
}
set input [file normalize $::env(FULL_GDS_INPUT)]
set output [file normalize $::env(FULL_GDS_OUTDIR)]
set top $::env(FULL_GDS_TOP)
if {![file isfile $input]} {
    error "GDS file not found: $input"
}
if {![file isdirectory $output]} {
    error "Create a new empty output directory: $output"
}
if {[llength [glob -nocomplain -directory $output * .*]] != 2} {
    error "Output directory must be empty: $output"
}

drc off
crashbackups disable
locking disable
set previous [pwd]
cd $output
gds read $input
load $top -dereference
extract do local
extract no capacitance
extract no coupling
extract no resistance
extract no adjust
extract warn all
extract all
ext2spice lvs
ext2spice blackbox off
ext2spice hierarchy on
ext2spice short resistor
ext2spice -o [file join $output "$top.raw_gds.spice"] "$top.ext"
feedback save [file join $output "feedback.txt"]
cd $previous
puts "Wrote raw GDS extraction to [file join $output "$top.raw_gds.spice"]"
