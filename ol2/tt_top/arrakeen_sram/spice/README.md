# GF180 Arrakeen SRAM transistor-level tests

These are ngspice testbenches for **our** Arrakeen `SP6TSRAM256x32`,
not the unrelated GF180 foundry SRAM. The logical 512x32 memory uses two
instances. Each physical bank is a 3.3 V, single-port macro with an 8-bit
address, 32-bit data and four active-high byte write enables.

**Voltage warning:** `SPSRAMFactory` uses `nfet_03v3`/`pfet_03v3`. Do not
apply the friend's 5 V supplies to this circuit. The PDK specifies nominal
3.3 V and a 3.63 V thin-oxide absolute gate-node DC limit; that limit is not
a recommended nominal operating voltage. The integrated design currently
connects the SRAM to the shared `vdpwr` net: verify the real chip supply,
all input levels, power sequencing and any level shifting independently.
The 5 V standard-cell timing library does **not** prove that `vdpwr` is 5 V,
but operating the SRAM at 5 V would exceed its device rating.

## Files

- `SP6TSRAM256x32.spice`: hierarchical **compiler schematic**, exported with
  the `SPSRAMFactory` parameters and name in `../generate_views.py`, using
  versions recorded in `../uv.lock`. It contains the compiler's 6T cell,
  decoder, write and read circuitry. It is **not** extracted from the
  submitted GDS; matching the checked-in GDS to this schematic requires an
  independent, unmodified LVS.
- `bitcell.spice`: writes 0 and 1 to the compiler's 6T cell; checks hold and
  differential reads using switched, capacitively loaded bitlines.
- `bank_functional.spice`: single bank; writes addresses 0/255, reads all
  32 bits (including bit 22), and checks a `0101` byte-write mask.
- `bank_retention.spice`: single bank; initializes data, stops the clock
  for approximately 1.8 µs, then reads both data polarities.
- `bank_address_pipeline.spice`: holds each write address across two
  edges, then checks the first and second read edges after an address change.
- `dual_bank_isolation.spice`: two macro instances; separately writes each
  and checks that a low-bank masked write does not alter the high bank. The
  bank enables are driven by testbench sources; this is **not** a
  transistor-level test of `tt_top`'s control logic or of physical supply
  isolation.
- `expected.json`, `check_results.py`: sampled 32-bit expected values and
  fail-closed checks. Missing, ambiguous or wrong output, simulator errors,
  missing transient data, and unexpected duplicate measurements fail.
- `bank_verilog_reference_tb.v`: independent replay of the first bank test
  against the compiler's behavioral Verilog model; it is not a SPICE model.
- `export_schematic.py`, `generate_benches.py`, `prepare_models.py`:
  reproducible generation, fixed port-order validation, and model setup.
- `RESULTS.md`: what has actually been simulated, with model and schematic
  hashes. A deck existing is not the same as a passing simulation.

The expected bank behavior follows the compiler's Verilog model: the address
is registered on a rising edge and each bank's `we` and `d` act on the
previously captured address. This is a **hypothesis under test**, not a
silicon guarantee. All SRAM locations start unknown: each tested word is
explicitly written before being checked. The bitcell uses ideal switches and
10 fF bitlines, while the bank tests use ideal input voltage sources and
10 fF output loads. The tests do not characterize physical drivers or timing.

## Run

Use Linux/WSL with ngspice compiled with KLU, Python 3, the exact GF180 PDK
revision used for the build, and the compiler dependencies in `../uv.lock`.
From `ol2/tt_top/arrakeen_sram`:

```sh
uv sync --project . --locked
uv run --project . --locked python spice/export_schematic.py spice/SP6TSRAM256x32.spice
python3 spice/generate_benches.py spice
python3 spice/test_spice_tools.py

# PDK_ROOT/gf180mcuD is the same PDK installation used for hardening.
python3 spice/prepare_models.py \
  --model-dir "$PDK_ROOT/gf180mcuD/libs.tech/ngspice" \
  --corner typical --output spice/models.spice
cd spice
ngspice -b -o bitcell.log bitcell.spice
python3 check_results.py bitcell bitcell.log
ngspice -b -o bank_functional.log bank_functional.spice
python3 check_results.py bank_functional bank_functional.log
ngspice -b -o bank_retention.log bank_retention.spice
python3 check_results.py bank_retention bank_retention.log
ngspice -b -o bank_address_pipeline.log bank_address_pipeline.spice
python3 check_results.py bank_address_pipeline bank_address_pipeline.log
ngspice -b -o dual_bank_isolation.log dual_bank_isolation.spice
python3 check_results.py dual_bank_isolation dual_bank_isolation.log
```

The single-bank tests write `bank_wave.dat`; move/rename it between runs
to retain both. `bitcell_wave.dat` and `dual_wave.dat` contain analog data and
`i(Vdd)`. A voltage sample is low at or below `0.3*VDD`, high at or above
`0.7*VDD`; intermediate values fail. Read differential checks require 0.1 V.
These are **test thresholds**, not foundry specifications. Do not call a
run a pass without both successful ngspice completion and the checker.
Full-bank transistor simulations can take substantial time and memory.

`prepare_models.py` accepts `typical`, `ss`, `ff`, `sf`, `fs`. Sweep process,
supply, temperature, edge rates and loads only within device limits; deck
defaults (`3.3 V`, `25 C`, 200 ns test cycle) are illustrative. Adjust the
deck's `VDD`/`.temp` and pass the same voltage to `check_results.py --vdd`.
Do not treat five deterministic corners as mismatch/Monte Carlo coverage.
The bitcell switch threshold is 1.65 V and assumes a 3.3 V test.

## What a pass does not prove

These decks validate only the compiler schematic and ideal testbench drives.
Before manufacturing, independently extract the **final GDS** and verify
transistor-level LVS/connectivity without netlist repair; repeat appropriate
tests on a validated PEX netlist with its actual port order, parasitics,
power grid and package loads. The included schematic is not the LEF-abstract
black box in the prior top-level LVS, nor the simulation-only patched GL
netlist. A successful 6T-cell test does not prove the full bank; the first
full-bank test actually **fails** the Verilog-model expectation (see
`RESULTS.md`). It also does not prove either bank's
power connection, the shared-power fault containment, the mux, the pad frame,
ESD, DRC, antenna, IR drop, reliability, yield, retention over lifetime,
all 512 words, or manufacturing readiness.

## References

- [GF180 chip operating conditions and device voltage limits](https://gf180mcu-pdk.readthedocs.io/en/latest/physical_verification/design_manual/drm_14_1.html).
- [GF180 MOSFET model parameters](https://gf180mcu-pdk.readthedocs.io/en/latest/analog/model_parameters/LV/LV_1_4_1.html).
- [GF180 PDK ngspice models and PDK structure](https://vlsida.github.io/chip-tutorials/gf180mcu.html).
- [ngspice user manual](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf).
- Local authoritative configuration: `../generate_views.py`, `../uv.lock`,
  and `rtl/SP6TSRAM256x32.v` at the mux repository root.
