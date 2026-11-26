import json
from pathlib import Path
import unittest

from check_results import check_values
from generate_benches import PORTS, macro_ports


HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))


def bank_log(name):
    lines = ["No. of Data Rows : 100"]
    for sample in MANIFEST[name]:
        fields = (("q", "expected"),) if name != "dual_bank_isolation" else (
            ("ql", "low"), ("qh", "high"))
        for prefix, field in fields:
            word = int(sample[field], 16)
            for bit in range(32):
                voltage = 3.3 if (word >> bit) & 1 else 0.0
                lines.append(f"{prefix}{bit}_{sample['sample']} = {voltage}")
    return "\n".join(lines)


class TestBenchTools(unittest.TestCase):
    def test_generated_schematic_interface(self):
        macro_ports((HERE / "SP6TSRAM256x32.spice").read_text(encoding="utf-8"))

    def test_deck_instance_pin_counts(self):
        for filename, instance_names in (
            ("bank_functional.spice", ("Xmem",)),
            ("bank_retention.spice", ("Xmem",)),
            ("bank_address_pipeline.spice", ("Xmem",)),
            ("dual_bank_isolation.spice", ("Xl", "Xh")),
        ):
            lines = (HERE / filename).read_text(encoding="utf-8").splitlines()
            for name in instance_names:
                instances = [line.split() for line in lines if line.startswith(name + " ")]
                self.assertEqual(len(instances), 1)
                self.assertEqual(len(instances[0]), len(PORTS) + 2)
                self.assertEqual(instances[0][-1], "SP6TSRAM256x32")

    def test_wrong_port_order_rejected(self):
        contents = ".subckt SP6TCell vdd vss\n.ends\n.subckt SP6TSRAM256x32 "
        contents += " ".join(reversed(PORTS)) + "\n.ends\n"
        with self.assertRaises(ValueError):
            macro_ports(contents)

    def test_missing_bitcell_rejected(self):
        with self.assertRaises(ValueError):
            macro_ports(".subckt SP6TSRAM256x32 " + " ".join(PORTS) + "\n.ends\n")

    def test_all_bank_cases(self):
        for name in ("bank_functional", "bank_retention", "bank_address_pipeline",
                     "dual_bank_isolation"):
            with self.subTest(name=name):
                self.assertEqual(check_values(name, bank_log(name), MANIFEST, 3.3), [])

    def test_wrong_bit_22_is_failure(self):
        name = "bank_functional"
        log = bank_log(name)
        line = next(s for s in log.splitlines() if s.startswith("q22_s0 ="))
        changed = "q22_s0 = " + ("0" if line.endswith("3.3") else "3.3")
        self.assertTrue(check_values(name, log.replace(line, changed), MANIFEST, 3.3))

    def test_missing_ambiguous_and_duplicate_fail(self):
        name = "bank_functional"
        log = bank_log(name)
        line = next(s for s in log.splitlines() if s.startswith("q0_s0 ="))
        self.assertTrue(check_values(name, log.replace(line, ""), MANIFEST, 3.3))
        self.assertTrue(check_values(name, log.replace(line, "q0_s0 = 1.65"), MANIFEST, 3.3))
        with self.assertRaises(ValueError):
            check_values(name, log + "\n" + line, MANIFEST, 3.3)

    def test_simulator_failure_and_no_rows_fail(self):
        with self.assertRaises(ValueError):
            check_values("bank_functional", "Error: convergence failed", MANIFEST, 3.3)
        with self.assertRaises(ValueError):
            check_values("bank_functional", "q0_s0 = 0", MANIFEST, 3.3)

    def test_disallow_5v(self):
        with self.assertRaises(ValueError):
            check_values("bank_functional", bank_log("bank_functional"), MANIFEST, 5.0)


if __name__ == "__main__":
    unittest.main()
