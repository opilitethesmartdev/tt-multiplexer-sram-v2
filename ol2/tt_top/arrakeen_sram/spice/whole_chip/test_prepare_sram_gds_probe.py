import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import prepare_sram_gds_probe as probe


class GdsBankProbeTest(unittest.TestCase):
    def test_pin_names_and_unknown(self):
        self.assertEqual(probe.port_map("vdd_uq0"), "vdd")
        self.assertEqual(probe.port_map("q[22]"), "q22")
        with self.assertRaises(ValueError):
            probe.port_map("vdd_uq1")

    def test_order_and_unchanged_stimulus(self):
        ports = (["clk", "vss", "vdd_uq0", "vdd"] +
                 [f"a[{n}]" for n in range(8)] +
                 [f"q[{n}]" for n in range(32)] +
                 [f"d[{n}]" for n in range(32)] +
                 [f"we[{n}]" for n in range(4)])
        original = probe.EXPECTED
        with TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "macro.spice"
            raw.write_text(".subckt SP6TSRAM256x32 " + " ".join(ports) + "\n.ends\n")
            probe.EXPECTED = hashlib.sha256(raw.read_bytes()).hexdigest()
            (root / "design.ngspice").write_text("* test")
            (root / "sm141064.ngspice").write_text("* test")
            template = root / "template.spice"
            template.write_text('.include "models.spice"\n'
                                '.include "SP6TSRAM256x32.spice"\n'
                                'Xmem old SP6TSRAM256x32\nVtest a0 0 3.3\n')
            try:
                result = probe.prepare(raw, root, template)
                self.assertIn("Xmem clk 0 vdd vdd a0 a1", result)
                self.assertIn(" SP6TSRAM256x32\nVtest a0 0 3.3\n", result)
                self.assertEqual(raw.read_text(),
                                 ".subckt SP6TSRAM256x32 " + " ".join(ports) + "\n.ends\n")
            finally:
                probe.EXPECTED = original


if __name__ == "__main__":
    unittest.main()
