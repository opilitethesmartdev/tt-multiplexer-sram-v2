# Local validation results

These are limited compiler-schematic and isolated-GDS-pilot simulations,
**not** manufacturing sign-off. See `README.md` for assumptions.

## Bitcell

ngspice 44.2, KLU, 3.3 V, 25 °C, 10 fF ideal bitlines:

| Measurement | Typical | SS |
|---|---:|---:|
| Written zero, held | 1.47e-8 V | 1.46e-8 V |
| Written one, held | 3.300 V | 3.300 V |
| Zero after read | 2.47e-7 V | 2.98e-7 V |
| One after read | 3.300 V | 3.300 V |
| Read-zero BLB−BL | 3.315 V | 3.318 V |
| Read-one BL−BLB | 3.315 V | 3.318 V |

Both runs pass `check_results.py bitcell`. The small bitline overshoot is
the transient response of this idealized switch/capacitor testbench; it is
not evidence that the array's real bitlines behave identically.

Model files used are from the local `c4m-arrakeen` checkout, not a verified
copy of the CI-pinned PDK:

| File | SHA-256 |
|---|---|
| `design.ngspice` | `b55dcc56441acbe9946d55368a2702310f5392c49f7ece7ee56bce0600aca56c` |
| `sm141064.ngspice` | `312429d2c7121f151316ae34bdd54f4aaac993558c84ad359af042864a8fe295` |
| Schematic used in runs | `ded51756ada5136e4777cd545d54bb30c300573c1260c99e284450612291e799` |
| Repository `SP6TSRAM256x32.spice` (LF endings) | `d1a8516ef17c698f8b04be36ef70edeab62346ed32bea8319d99494a89bbd6ae` |

The initial bitcell and bank tests used Windows line endings and one
additional trailing blank line; normalized circuit text otherwise matches
the repository version. The write-address test used the repository version.

The shipped SRAM GDS in the mux repository and the GDS from workflow
`45835066447` both hash to
`8bd69f88490f96fd5ba8a84c25405d55c3ff0780ce00a73e4af965603fac680e`.
That establishes those two GDS files match, **not** that either is LVS-clean
against this schematic.

## Full macro

The real 256x32 compiler schematic **fails** `bank_functional` at 3.3 V,
25 °C, typical, using the model files above. The simulator finished with
1832 transient rows; these are full 32-bit decoded output samples:

| Sample | Time | Expected from Verilog model | SPICE observed |
|---|---:|---:|---:|
| s0 | 980 ns | `aa34aa78` | `55aa55aa` |
| s1 | 1180 ns | `55aa55aa` | `aa34aa78` |
| s2 | 1380 ns | `aa34aa78` | `55aa55aa` |

`bank_verilog_reference_tb.v` independently replays the same sequence
against `rtl/SP6TSRAM256x32.v` and passes the three expected words with
Icarus Verilog. That confirms the expectations match the behavioral model;
it does not establish which circuit behavior is intended.

The follow-up `bank_address_pipeline.spice` test holds each write address
across two edges before changing it, then checks the first and second
read edges. It **passes** at the same corner:

| Sample | Time | Expected | SPICE observed |
|---|---:|---:|---:|
| s0, first read at address 0 | 980 ns | `aa55aa55` | `aa55aa55` |
| s1, second read at address 0 | 1180 ns | `aa55aa55` | `aa55aa55` |
| s2, first read at address 255 | 1380 ns | `55aa55aa` | `55aa55aa` |
| s3, second read at address 255 | 1580 ns | `55aa55aa` | `55aa55aa` |

`bank_write_address.spice` initializes both words, changes the address at a
write edge, then reads both locations to distinguish current versus
previous write address. Its behavioral Verilog reference passes, but the
SPICE schematic **fails** at the same PVT point:

| Address read | Behavioral expected | SPICE observed |
|---|---:|---:|
| Previous address 0 | `aa55aa55` | `00000000` |
| Current address 255 | `00000000` | `aa55aa55` |

Thus, under this stimulus, the compiler's transistor schematic writes the
current address, while its supplied Verilog model writes the previous
latched address. The integrated wrapper delays write enable and data but not
the address. This is a serious SRAM functional mismatch, not a full-chip
simulation result; confirm the final GDS with an unmodified physical
extraction/LVS before deciding a hardware change. Do not alter expected
values merely to make tests pass or claim the SRAM works from the GL tests.

Full-bank retention and two-bank isolation have not been run with the real
macro. Their decks do run with a deliberately nonfunctional dummy macro,
and the checker correctly rejects its wrong outputs.

## SRAM GDS-extraction write-address probe

The same write-address stimulus was run against the separate SRAM GDS
child-flatten extraction, using ngspice 44.2, the CI-pinned GF180MCUd
`typical` models, 3.3 V and 25 °C. The extracted 80-pin interface has both
`vdd` and `vdd_uq0`; the **testbench explicitly ties both to 3.3 V**, an
unverified assumption about external supply connections. The extraction
has not passed independent LVS and does not include extracted parasitics.
It is not the complete routed chip.

The unmodified behavioral expectation fails on the GDS-extracted circuit:

| Address read | Compiler Verilog expected | GDS-extracted SPICE observed |
|---|---:|---:|
| Previous address 0 | `aa55aa55` | `00000000` |
| Current address 255 | `00000000` | `aa55aa55` |

This is consistent with the earlier compiler-schematic transistor result,
but it does not resolve timing margins or prove the supply mapping. The raw
log and waveform are `whole_chip/artifacts/sram_gds_write_address.log.gz`
and `whole_chip/artifacts/sram_gds_write_address_wave.dat.gz`; the actual
deck and a fail-closed name-based generator are also in `whole_chip/`.
The original compiler Verilog and expected results remain unchanged.
The uncompressed log SHA-256 is
`19a93df94df15c6a8416869fc7302a6e6e1d2608819f961130612b744e20d209`;
the waveform SHA-256 is
`05ae14e34903876333532e52e4292ae36a5f75c582db784cb5f391b5df96f973`.
