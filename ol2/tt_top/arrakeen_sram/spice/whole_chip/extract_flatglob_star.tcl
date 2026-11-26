# The requested sequence, with only the input path parameterized.
# Run in an empty directory with Magic and the correct PDK .magicrc:
#   FULL_GDS_INPUT=/absolute/path/tt_gf_wrapper.gds magic ... < this-file
#
# On run 45835066447, flatglob * matched the top cell itself and this
# sequence produced "There is nothing here to extract" and no SPICE.
gds flatglob *
gds read $::env(FULL_GDS_INPUT)
load tt_gf_wrapper
select top cell
extract all
ext2spice lvs
ext2spice -o tt_gf_wrapper_from_gds.spice
quit -noprompt
