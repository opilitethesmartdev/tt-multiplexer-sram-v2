# Whole-chip GDS extraction and exploratory SPICE attempt

**No whole-chip functional result was obtained. Do not treat this as LVS,
PEX, or evidence that the chip is safe to manufacture.**

## Inputs and extraction

- Chip: CI run `45835066447`, mux commit `2914d8a`, not the newer candidate.
- Original `final/gds/tt_gf_wrapper.gds` SHA-256:
  `2117d03c0758f77ef09e555877f68f730747b29d89e82bc2907dd2b111c0918f`.
- Magic 8.3.677, no GUI, GF180MCUd PDK
  `1689ac3f2dc763876eaf967227c7dfe831b031ae`; direct GDS read,
  hierarchical device extraction, no netlist repair, parasitic capacitance
  and resistance disabled, short resistors preserved.
- Raw full-GDS SPICE SHA-256:
  `87b2ef7725362b3d7d5ffff650acb6c39ca0553a32a6879f46a8a20003865c72`.
  The unmodified file is `artifacts/raw_tt_gf_wrapper_from_gds.spice.gz`.
- Magic feedback SHA-256:
  `65278a171bef493cb57eecb8a8475480661b24fe235c24b11ec16bdcbd5853d6`.
  The unmodified file is `artifacts/raw_full_gds_feedback.txt.gz`.

The extraction contains 390 subcircuits and 25,505 hierarchical `X` lines.
Expanding the hierarchy by counting repeated references estimates 847,235
MOS device-subcircuit instances and 12,926 diode elements; this is a
netlist estimate, not a transistor LVS count. Magic reported 129,538
feedback warnings. Counting the feedback file shows all 129,538 messages
are `Warning: node labels should be inside overlap area`. They are not all
distinct DRCs or automatically confirmed shorts, but their effect on
extracted connectivity has not been resolved.

The raw full-GDS extraction, like the prior DEF/LEF extraction, associates
`sram_lo/q[22]` with `vssd2`. Those two Magic extraction modes are not
independent. However, an additional **KLayout drawn-geometry check**, not
using Magic net names or extraction, finds a metal/via path from the GDS
SRAM `q[22]` label to the GDS `VSS` label of the nearby standard-cell mux.
This strongly indicates a physical short in the baseline GDS. It does not
establish whether the newer candidate has the same defect.

### Independent geometry witness

`trace_q22_short.py` checks the exact GDS hash, instance transformations,
GDS text labels and actual drawn polygons on GF180 metal/via layers. The
SRAM and root Metal3 polygons overlap by **0.010 × 0.140 µm** at
`(913.920, 3230.080)`–`(913.930, 3230.220)` µm. Within a 20 × 30 µm
window, it finds a positive-area path from the SRAM label on M3 through
Via2, M2 and Via1 to the cell VSS label on M1. The shown bounding boxes
are for whole merged polygons, not assertions that the entire box is filled:

```text
M3 (913.650, 3229.940, 914.300, 3244.270)
V2 (913.980, 3229.950, 914.240, 3230.210)
M2 (913.920, 3229.940, 914.300, 3230.220)
V1 (913.980, 3229.950, 914.240, 3230.210)
M1 (905.000, 3228.895, 925.000, 3231.420)
```

Reproduce with KLayout Python bindings:

```sh
python3 test_trace_q22_short.py
python3 trace_q22_short.py /path/to/tt_gf_wrapper.gds
```

The second command intentionally exits 1 for the observed short. The
synthetic tests pass, including missing-via and edge-only cases. This
targeted check is not full-chip DRC/LVS and cannot prove the rest of the
layout safe. A corrected build needs independent, unmodified physical
verification; never apply an LVS netlist rewrite to conceal this path.

### Likely power-routing mechanism

In the same run's original final DEF, which uses 2000 units/µm, the `vgnd`
special net contains the Via1–Via3 stack at `(1828220, 6460160)`:

```text
NEW Metal3 0 + SHAPE STRIPE ( 1828220 6460160 ) vg_7dc3c90f_1x1
NEW Metal2 0 + SHAPE STRIPE ( 1828220 6460160 ) vg_7dc3c8e9_1x1
NEW Metal1 0 + SHAPE STRIPE ( 1828220 6460160 ) vg_7dc400a5_1x1
```

The stack center is on the SRAM bottom boundary; its Metal3 enclosure
overlaps the `q[22]` Metal3 geometry. `StdCellPower` in `odb_route.py`
inserts such stacks, while its macro path test checks the riser center and
vertical interval rather than the full via enclosure at a boundary. This is
a plausible mechanism, not yet a proven complete root-cause analysis.
There is no difference in `odb_route.py` between baseline mux `2914d8a`
and candidate `131bf55`. Placement can change, so this does not establish
the candidate has the same short. A robust fix needs enclosure-aware
clearance checks against signal geometry and independently verified power
connectivity, not merely shifting this one known via or repairing LVS.

The same extracted top connects each SRAM macro's `vdd` port to a distinct
net (`top_I.sram_lo_I/vdd` or `top_I.sram_hi_I/vdd`) that appears on no
other top-level component, while `vdd_uq5` connects to `vccd2`. In this
SPICE representation the two `vdd` nets therefore have no top-level
supply source. Whether this indicates a physical disconnect or an
extraction/label artifact is unresolved; do not silently tie these nets
when claiming to simulate unmodified layout.

## Ngspice attempts

The exploratory test instantiates the exact extracted whole-chip top,
selects the factory-test tile, and drives its bidirectional inputs through
1 kohm resistors while observing pad voltages, outputs and source currents.
It uses a 3.3 V source for all supply groups and grounds all ground groups;
those are testbench assumptions, not a validated pad-ring or package model.
The design contains no SRAM-capable user tile, so this cannot exercise the
SRAM through the normal tile interface.

The standard-cell devices are **already represented in the GDS-extracted
subcircuits**; adding the complete standard-cell SPICE library unchanged
would redefine 11 existing cells. The probe loads the exact PDK device
model corner (`typical` plus `diode_typical`) instead. The separate
DEF/LEF `final/spice` abstract requires the corresponding external cell and
macro definitions, with duplicate stubs and positional pin order handled.

| Attempt | Result |
|---|---|
| Unmodified GDS SPICE | ngspice 44.2 stopped during parsing: `Too many parameters` for an SRAM subcircuit because Magic's `$SUB` node token was interpreted as a comment. |
| Syntax-only normalized copy | 35 `$SUB` tokens were bijectively renamed to `__magic_substrate`, with no node merges, rewiring or change to the original. The copied netlist SHA-256 is `98d2e2a5fc23f78ddceb890db021f70f73a104a67d1e65c9292cf01b723c1dcc`. Ngspice then failed with `malloc: can't allocate 1691 bytes` under a 4.5 GB virtual-memory limit, before producing transient data. |

The original logs are `artifacts/factory_unmodified_attempt.log.gz` and
`artifacts/factory_normalized_attempt.log.gz`. A larger-memory machine or
a verified hierarchical/mixed-signal methodology is needed; replacing or
omitting parts of the chip without proving equivalence would not be a
whole-chip transistor simulation.

PDK files used:

| File | SHA-256 |
|---|---|
| `design.ngspice` | `7e222f050318388f37543a64fbd0be55cc15e4b93f57501a09f7c159c4c9e561` |
| `sm141064.ngspice` and `.spice` | `69a7ab877344a6d477fdd11440457f64e7ad88a624504a737a161da463de8bc8` |
| standard-cell `spice` | `0e126c5e10e45e705a83acfa47f6fd2c4ef0357e99c339dec43cdc16bfb13664` |
| `gf180mcuD.tech` | `3393fd8c487b80926d0a0235694a3523df8a8d88614c773b814a02d8f2070a25` |

## Reproduce the exploratory deck

With the matching PDK and sufficient resources, in this directory:

```sh
gzip -dc artifacts/raw_tt_gf_wrapper_from_gds.spice.gz > raw_gds.spice
python3 normalize_magic_spice.py raw_gds.spice normalized.spice
python3 prepare_factory_probe.py --raw-spice raw_gds.spice \
  --simulation-copy normalized.spice \
  --model-dir "$PDK_ROOT/gf180mcuD/libs.tech/ngspice" \
  --output factory_probe.spice --ack-extraction-warnings
ngspice -b -o factory_probe.log factory_probe.spice
python3 check_factory_probe.py factory_probe.log
```

The checker fails on missing data, ambiguous logic or incorrect loopback
samples, and reports the maximum sampled UIO source current. It does not
assert a current limit because the actual interface specification is not
established. Even a pass would cover only a small part of this design.
