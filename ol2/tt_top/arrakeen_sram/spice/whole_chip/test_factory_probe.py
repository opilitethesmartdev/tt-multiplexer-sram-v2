import unittest
from pathlib import Path

from check_factory_probe import check
from prepare_factory_probe import deck, map_port, validate_flat_ports, FLAT_SUPPLY_PORTS
from normalize_magic_spice import normalize


def good_log():
    lines = ["No. of Data Rows : 123"]
    for phase, word in (("a", 0xa5), ("b", 0x5a)):
        for bit in range(8):
            value = 3.3 if (word >> bit) & 1 else 0
            lines += [f"input{bit}_{phase} = {value}",
                      f"output{bit}_{phase} = {value}",
                      f"current{bit}_{phase} = 1e-9"]
    return "\n".join(lines)


class FactoryProbeTests(unittest.TestCase):
    def test_pin_mapping(self):
        self.assertEqual(map_port("pad_raw[37]"), "p37")
        self.assertEqual(map_port("vccd2"), "vdd")
        self.assertEqual(map_port("vssio_uq2"), "0")
        with self.assertRaises(ValueError):
            map_port("unknown_supply")

    def test_flat_port_set_is_fail_closed(self):
        ports = [f"pad_raw[{n}]" for n in range(74)] + sorted(FLAT_SUPPLY_PORTS)
        validate_flat_ports(ports)
        with self.assertRaises(ValueError):
            validate_flat_ports(ports[:-1] + [ports[0]])
        with self.assertRaises(ValueError):
            validate_flat_ports(ports[:-1])

    def test_valid_log(self):
        errors, current = check(good_log())
        self.assertFalse(errors)
        self.assertAlmostEqual(current, 1e-9)

    def test_deck_preserves_caller_port_order(self):
        text = deck(Path("layout.spice"), Path("design.spice"),
                    Path("models.spice"),
                    ["pad_raw[9]", "vccd2", "vssd2", "pad_raw[0]"])
        self.assertIn("Xchip p9 vdd 0 p0 tt_gf_wrapper", text)
        self.assertIn("Ruio0 src0 p37 1k", text)

    def test_contention_or_wrong_output(self):
        log = good_log().replace("input0_a = 3.3", "input0_a = 0")
        self.assertTrue(check(log)[0])
        log = good_log().replace("output1_b = 3.3", "output1_b = 1.65")
        self.assertTrue(check(log)[0])

    def test_missing_failure_or_unsafe_voltage(self):
        self.assertTrue(check(good_log().replace("current0_a = 1e-9", ""))[0])
        with self.assertRaises(ValueError):
            check("Error: simulator failure")
        with self.assertRaises(ValueError):
            check(good_log(), 5.0)

    def test_substrate_rename_is_bijective(self):
        raw = b".subckt foo a $SUB\nX1 a $SUB cell\n.ends\n"
        normalized, count = normalize(raw)
        self.assertEqual(count, 2)
        self.assertEqual(normalized.replace(b"__magic_substrate", b"$SUB"), raw)
        with self.assertRaises(ValueError):
            normalize(raw + b"R1 __magic_substrate a 1k\n")
        with self.assertRaises(ValueError):
            normalize(raw + b"* unrelated $ comment\n")


if __name__ == "__main__":
    unittest.main()
