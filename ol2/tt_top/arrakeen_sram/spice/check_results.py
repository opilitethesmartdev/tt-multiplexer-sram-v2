#!/usr/bin/env python3
"""Fail closed on absent, ambiguous, non-finite, or incorrect measurements."""
import argparse
import json
import math
from pathlib import Path
import re
import sys

MEASURE = re.compile(r"(?im)^\s*([a-z][a-z0-9_]*)\s*=\s*"
                     r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)")


def check_values(test, log, manifest, vdd):
    if not math.isfinite(vdd) or not 0 < vdd <= 3.63:
        raise ValueError("VDD must be positive and at most 3.63 V for this 3.3 V test")
    if re.search(r"(?im)^\s*(?:fatal|error|doanalyses:)", log):
        raise ValueError("simulator log reports an error")
    if not re.search(r"(?im)^\s*No\. of Data Rows\s*:\s*[1-9]\d*", log):
        raise ValueError("transient data row count is missing or zero")
    matches = MEASURE.findall(log)
    measurements = {}
    for name, raw in matches:
        name = name.lower()
        if name in measurements:
            raise ValueError(f"duplicate measurement {name}")
        measurements[name] = float(raw)
    errors = []

    def get(name):
        value = measurements.get(name)
        if value is None or not math.isfinite(value):
            errors.append(f"{name}: missing or non-finite")
            return None
        return value

    def logic(name, expected):
        value = get(name)
        if value is None:
            return
        if expected == 0 and not -0.05 * vdd <= value <= 0.3 * vdd:
            errors.append(f"{name}: expected low, got {value:.6g} V")
        if expected == 1 and not 0.7 * vdd <= value <= 1.05 * vdd:
            errors.append(f"{name}: expected high, got {value:.6g} V")

    if test == "bitcell":
        logic("cell_zero", 0)
        logic("cell_one", 1)
        logic("cell_after_read0", 0)
        logic("cell_after_read1", 1)
        for name, positive, negative in (
            ("read0", "cell_read0_blb", "cell_read0_bl"),
            ("read1", "cell_read1_bl", "cell_read1_blb"),
        ):
            plus, minus = get(positive), get(negative)
            if plus is not None and minus is not None and plus - minus < 0.1:
                errors.append(f"{name}: differential is {plus-minus:.6g} V; need >= 0.1 V")
    elif test == "dual_bank_isolation":
        for sample in manifest[test]:
            for bank, field in (("l", "low"), ("h", "high")):
                word = int(sample[field], 16)
                for bit in range(32):
                    logic(f"q{bank}{bit}_{sample['sample']}", (word >> bit) & 1)
    else:
        if test not in manifest:
            raise ValueError(f"unknown bank test: {test}")
        for sample in manifest[test]:
            word = int(sample["expected"], 16)
            for bit in range(32):
                logic(f"q{bit}_{sample['sample']}", (word >> bit) & 1)
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("test", choices=("bitcell", "bank_functional", "bank_retention",
                                        "bank_address_pipeline", "dual_bank_isolation"))
    parser.add_argument("log", type=Path)
    parser.add_argument("--expected", type=Path, default=Path("expected.json"))
    parser.add_argument("--vdd", type=float, default=3.3)
    args = parser.parse_args()
    manifest = json.loads(args.expected.read_text(encoding="utf-8"))
    try:
        errors = check_values(args.test, args.log.read_text(
            encoding="utf-8", errors="replace"), manifest, args.vdd)
    except ValueError as e:
        parser.error(str(e))
    if errors:
        print(f"FAIL {args.test}:")
        print("\n".join(errors))
        return 1
    print(f"PASS {args.test} (measurement thresholds only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
