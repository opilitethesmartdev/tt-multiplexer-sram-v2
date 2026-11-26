#!/usr/bin/env python3
"""Check exploratory full-GDS factory loopback measurements.

A passing result is not LVS, PEX, SRAM coverage or silicon sign-off.
"""
import argparse
import math
from pathlib import Path
import re
import sys

MEASUREMENT = re.compile(
    r"(?im)^\s*([a-z][a-z0-9_]*)\s*=\s*"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)"
)


def check(log, vdd=3.3):
    if not math.isfinite(vdd) or not 0 < vdd <= 3.63:
        raise ValueError("invalid 3.3 V-domain supply")
    if re.search(r"(?im)^\s*(?:fatal|error|doanalyses:)", log):
        raise ValueError("ngspice reports an error")
    if not re.search(r"(?im)^\s*No\. of Data Rows\s*:\s*[1-9]\d*", log):
        raise ValueError("transient simulation did not produce data")
    values = {}
    for name, raw in MEASUREMENT.findall(log):
        name = name.lower()
        if name in values:
            raise ValueError(f"duplicate measurement: {name}")
        values[name] = float(raw)
    errors = []
    currents = []
    for phase, word in (("a", 0xa5), ("b", 0x5a)):
        for bit in range(8):
            expected = (word >> bit) & 1
            for prefix in ("input", "output"):
                key = f"{prefix}{bit}_{phase}"
                value = values.get(key)
                if value is None or not math.isfinite(value):
                    errors.append(f"{key}: missing or non-finite")
                elif expected == 0 and not -0.05*vdd <= value <= 0.3*vdd:
                    errors.append(f"{key}: expected low, got {value:.6g} V")
                elif expected == 1 and not 0.7*vdd <= value <= 1.05*vdd:
                    errors.append(f"{key}: expected high, got {value:.6g} V")
            current_key = f"current{bit}_{phase}"
            current = values.get(current_key)
            if current is None or not math.isfinite(current):
                errors.append(f"{current_key}: missing or non-finite")
            else:
                currents.append(abs(current))
    return errors, max(currents, default=0.0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--vdd", type=float, default=3.3)
    args = parser.parse_args()
    try:
        errors, peak_current = check(args.log.read_text(encoding="utf-8", errors="replace"),
                                     args.vdd)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Maximum sampled absolute external UIO source current: {peak_current:.6g} A")
    print("No current limit is asserted; inspect this value against actual interface requirements.")
    if errors:
        print("FAIL: exploratory factory loopback")
        print("\n".join(errors))
        return 1
    print("PASS: exploratory factory-loopback voltage samples only; not sign-off.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
