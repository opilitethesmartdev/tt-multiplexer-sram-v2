# Recorded simulations

These are the unmodified ngspice 44.2 logs and `wrdata` output compressed
with gzip. They are provided for inspection, not as a manufacturing sign-off.
See `../RESULTS.md` for conditions, model hashes, interpretation and limits.

| File prefix | Contents |
|---|---|
| `bitcell-typical` | Typical 3.3 V, 25 °C bitcell log and analog waveform |
| `bitcell-ss` | Slow-slow 3.3 V, 25 °C bitcell log and analog waveform |
| `bank-functional-typical` | Typical 3.3 V, 25 °C full-bank log and waveform; the checker **fails** |
| `bank-address-pipeline-typical` | Typical 3.3 V, 25 °C full-bank log and waveform; the checker passes |
| `bank-write-address-typical` | Typical 3.3 V, 25 °C write-address diagnostic; the checker **fails** |

Each `wrdata` waveform has a time column followed by a value column for
each saved signal. The source decks list the signal order. The local GF180
model files themselves are not included: their hashes are in `RESULTS.md`.
The files `models.spice` contain local absolute paths and are not published;
regenerate them with `../prepare_models.py`.
