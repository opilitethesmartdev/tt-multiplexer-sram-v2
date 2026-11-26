import unittest

from prepare_sram_hold_probe import variant


class HoldProbeTest(unittest.TestCase):
    def test_only_data_and_we_change(self):
        lines = ["* Exploratory GDS pilot:", "Va0 a0 0 PWL(1249n 0 1250n 1)"]
        lines += [f"Vd{n} d{n} 0 PWL(1249n 1 1250n 0)" for n in range(16)]
        lines += [f"Vwe{n} we{n} 0 PWL(1249n 1 1250n 0)" for n in range(4)]
        lines += ["wrdata bank_wave.dat v(a0)"]
        output = variant("\n".join(lines) + "\n", 2)
        self.assertIn("Va0 a0 0 PWL(1249n 0 1250n 1)", output)
        self.assertEqual(output.count("1103n 1 1104n 0"), 20)
        self.assertIn("bank_hold_2ns.dat", output)

    def test_fail_closed(self):
        with self.assertRaises(ValueError):
            variant("not a deck", 2)
        with self.assertRaises(ValueError):
            variant("* Exploratory GDS pilot:\n", 2)
        with self.assertRaises(ValueError):
            variant("* Exploratory GDS pilot:\n", 0)


if __name__ == "__main__":
    unittest.main()
