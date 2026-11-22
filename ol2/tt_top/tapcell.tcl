#
# Well-tap insertion for tt_top
#
# Copyright (c) 2023 Sylvain Munaut <tnt@246tNt.com>
# SPDX-License-Identifier: Apache-2.0
#

source $::env(SCRIPTS_DIR)/openroad/common/io.tcl
read_current_odb

# Well taps only: the filltie cell is the PDK's well/substrate tap. Endcap
# cells are not inserted because the core edge is covered by the macro columns
# in the branch rows and an endcap in a macro-free band would be left without
# a power rail.
tapcell \
	-distance $::env(FP_TAPCELL_DIST) \
	-tapcell_master $::env(WELLTAP_CELL) \
	-halo_width_x 10 \
	-halo_width_y 10

write_views
