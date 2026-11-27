# Shared SRAM (GF180) — silicon-safety review and fixes

This branch fixes the defects found while checking whether the shared-SRAM
multiplexer build is safe to tape out, and adds checks so the same classes of
defect fail the build instead of reaching silicon.

Everything below was verified on a full local `tt_top` hardening run (same
LibreLane/Nix toolchain and PDK version as CI, CI's own mux/ctrl/ROM macros),
and on the foundry's own rule decks from the wafer.space precheck.

## TL;DR

| | Before (CI `main`) | After (this branch) |
|---|---|---|
| Metal shorts in the GDS | **2** (SRAM q[22]→GND, power-gate ctrl→VDD) | **0** |
| LVS | "match" — only because a shorted pin was patched back in the netlist | match, no patching |
| SRAM request bus when another project is selected | **floating** (random writes possible) | held at 0, request gated |
| Routing DRC | 0 (by luck, last iteration) | 0, at 2 and 4 threads |
| Global routing overflow | 1,257 (guides through tile obstructions) | 0, congestion disallowed |
| Foundry antenna deck | 679 | **12** (4 on pad nets) |
| Foundry DRC deck | 65,475 | **135** (73 in this design, see §6) |
| SRAM read/write simulation | none | 512×32, both banks, byte masks: PASS |

## 1. Defects that could break chips

### 1.1 SRAM `q[22]` shorted to ground

The only standard-cell row in the 7.6 µm gap between the two stacked SRAM
banks had its power rail exactly on `sram_lo`'s bottom edge, where all SRAM
signal pins start. `StdCellPower` placed a Via1–3 stack on that rail; its pads
reached 0.14 µm into the macro and one landed on the `q[22]` pin. Bit 22 of
the lower 256 words would always read 0, and the SRAM output driver would
drive into a short.

LVS did see it: the extracted netlist had `q[22]` on `vssd2`. `MergeWellNets`
then moved the pin back to its DEF net before netgen ran, so LVS passed.

**Fix:** a 2 µm hard placement halo around every hard macro (no row rail on a
macro edge); via stacks and risers keep 0.3 µm from every macro; a rail
without power is now a build error; `MergeWellNets` no longer moves signal
pins off a supply (it warns and lets LVS fail).

### 1.2 Tile 14_1 power-gate `ctrl` shorted to VDD

`MacroPowerVias._tie_neighbour` connected the ringless first vdpwr stripe with
a Metal4 "L" starting on the power gate's VPWR pin. That pin is capped by the
gate's own `ctrl` bar 0.3 µm above it, so the L ran through `ctrl`:
`tt_um_gatoware_prometheus_lite` could never be switched off and the mux
`um_pg_ena[1]` driver fought VDD whenever it drove low.

**Fix:** the tie now drops a Via4 from the stripe in a macro-free column and
routes an L that is checked against all foreign Metal4 pins, macro outlines
and special wiring.

### 1.3 SRAM request bus floating

Each SRAM-capable mux drives the spine's SRAM bus through tri-state buffers
enabled only while its branch is selected. Only branch 11 has SRAM on this
chip, so whenever any other project was selected the bus floated — straight
into the SRAM chip-select / write-enable / address / data logic and the SRAM's
address pins (random writes, floating CMOS inputs). Synthesis had also
optimised the side-select away because the bottom spine bus has no driver.

**Fix (`rtl/tt_top.v`):** decode which SRAM branch is selected exactly like
`tt_mux` does, accept requests only from a selected SRAM branch, and hold each
side's bus low with weak tri-state drivers (the mux's own bus-pull technique)
while no SRAM branch on that side is selected.

## 2. Manufacturability fixes (foundry rule decks)

| Issue | Cause | Fix |
|---|---|---|
| V3.2b / V4.2b (49,700) | `ViaGenerator` used single-cut spacing for 4×4+ arrays | 0.36 µm spacing for 4×4+ arrays, else cap at 3 cuts |
| M4.2a (~15,800) | tie-off stubs 0.28 µm into 0.30 µm pins → 0.01 µm notches | pin-width patch inside the stub wire |
| V4.2a | single Via4s dropped between pdngen's arrays | skip pins already tied; risers keep 0.36 µm from every via |
| M2.3 / M3.3 (680) | riser via pads below 0.1444 µm² | 0.4 × 0.4 µm Metal2/Metal3 pads |
| M4.1 necks | same-net Metal4 from different steps meeting at corners | same-net riser spacing + neck patch pass |
| NP.2 / PP.2 / DV.5 | gaps between cells, no fillers | filler cells in gaps between cells |
| DF.13 / DF.14 | cells with no well tap in reach (latch-up) | taps placed by true distance, searched along the row |
| Antenna (679) | 1.4 mm `l_k_zero` tie nets; long wires into SRAM 3.3 V gates; no repair | per-bit tie cells, antenna diodes on SRAM inputs/outputs and the spine decode; measured `ANTENNAGATEAREA`/`DIFFAREA` in the SRAM LEF |
| Routing guides through tile obstructions | 30 % track reserve + congestion allowed | 5 % reserve, congestion disallowed (0 overflow) |
| Density (87) | no fill anywhere | PDK fill script in the submission flow (playground repo) |

## 3. New safeguards

* **`TT.Top.GdsShortCheck`** (`ol2/tt_top/gds_short_check.py`): KLayout
  extracts Metal1–5 connectivity straight from the streamed GDS and fails on
  supply-to-supply shorts, signals merged into a supply, and non-supply macro
  pins on a supply. It reports both shorts above on the old GDS and none now.
  It never reads or edits a netlist, so netlist repairs cannot mask it.
* **`make sim_sram`**: a self-checking BIST tile in branch 11 writes and reads
  all 512 words through the real `tt_mux`/`tt_ctrl`/`tt_top` RTL, then selects
  a different project and checks the SRAM bus stays at 0 and the contents do
  not change. Three fault injections (q[22] stuck low, bank select stuck,
  decode stuck selected) must and do fail.
* StdCellPower and WellTaps report every unpowered rail / untapped cell.

## 4. Verification on the final build

* Routing DRC 0; global routing overflow 0.
* GDS short check: 0 (also 0 after fill).
* LVS: circuits match uniquely, without netlist patching.
* `make sim_sram`: ALL PASS, 3/3 fault injections detected.
* Formal (`formal_tristate`, `formal_connectivity`): PASS.
* Playground RTL test (`test_mux`) and gate-level test (`test_mux_gl`) on the
  new netlist: 2/2 PASS each.
* Foundry decks: see the table in §5.

## 5. Still open — needs the chip owner

1. **Pad connection points (highest priority).** The `pad_raw[]` pins are
   placed by `CustomIOPlacement` from `gf180_pin_order.cfg`, evenly along the
   edges, not at the openframe template's pad positions. Neither repo
   assembles a pad ring. Whoever builds the final chip must confirm each
   `pad_raw` pin lands on its pad; if not, the I/O is unconnected.
2. **The precheck checks the wrong file.** It runs on the core
   (`tt_gf_wrapper`, 3166×4766 µm) but expects a full slot-sized chip with seal
   ring and pad ring (3932×5122 µm, origin at 0,0). It cannot pass until it
   runs on the assembled chip.
3. **No project uses the SRAM.** All tiles have `uses_sram: false`. Only
   branch 11 can reach the SRAM (the other SRAM branches 5/7/15 are masked).
4. **Metal4 coverage (M4.4, needs > 30 %).** After the PDK fill it is about
   23 %: the fill script will not put dummy Metal4 under the dense Metal5 PDN
   stripes (foundry guideline DM.4–DM.7, not enforced by the deck). Either
   accept fill under the stripes or add Metal4 to the PDN — a decision for the
   owner.
5. **Remaining foundry DRC/antenna items**, listed in §6.
6. **The SRAM macro itself** is unverified in silicon: the simulation model
   was not checked against the Arrakeen macro's transistor-level behaviour, and
   its generator script post-processes with sky130 layer numbers on a GF180
   layout (a no-op), which likely explains the implant-area errors inside the
   macro.
7. Timing sign-off uses 5 V corners while the digital supply domain is
   named/gated as 3.3 V; confirm the actual supply voltage.

## 6. Final foundry check results

Foundry decks from the wafer.space precheck (PDK `2fdf40d5`), run on the
final `tt_gf_wrapper` GDS (unfilled; fill is floating and was checked
separately: 0 shorts after fill).

**DRC: 135** (was 65,475)

| Rule | Count | Where / why |
|---|---|---|
| M3.2a / M3.2b / M4.2a / M4.2b | 44 | inside `gf180mcu_ws_ip__qrcode_id`, wafer.space's ID placeholder that their precheck replaces — not this design |
| M3.2a | 18 | die edge: `fix_power_pins` leaves 0.1 µm between the template power pins and the `pad_raw` pins; depends on the pad-ring question (§5.1) |
| DF.13_MV / DF.14_MV | 30 | cells in densely packed rows still beyond 15 µm of a well/substrate tap (latch-up rule) — WellTaps warns about them |
| M4.2a | 40 | remaining Metal4 spacing at power-strap / mux-pin junctions |
| NP.2 / NW.2a_LV / DV.5 | 3 | single implant/well spacing spots between cells |

**Antenna: 12** (was 679). 4 are on `pad_raw` nets (protected by the pad
cells' ESD diodes in the assembled chip); 8 are thick-gate Metal2/Metal3
ratios on individual glue nets and one spine select line.

**Density: 231 after the PDK fill** (was 87 before fill): 230 DCF.1a markers on
the core's outer edge strips, where the pad ring attaches, and M4.4 (§5.4).

**Magic DRC** in the precheck is advisory (`ERROR_ON_MAGIC_DRC: False` in
wafer.space's own precheck); its notch reports dropped with the fixes above.

