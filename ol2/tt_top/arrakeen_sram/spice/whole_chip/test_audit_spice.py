import gzip
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from audit_spice import audit, parse_subcircuits


class AuditTests(unittest.TestCase):
    def test_continuations_preserve_port_order(self):
        blocks = parse_subcircuits(".subckt top a\n+ b c\nX1 a b c child\n.ends\n", "a")
        self.assertEqual(blocks[0].ports, ["a", "b", "c"])
        self.assertEqual(list(blocks[0].instances()), [("X1", ["a", "b", "c"], "child")])

    def test_dangling_continuation_fails(self):
        with self.assertRaises(ValueError):
            parse_subcircuits("+ a\n", "a")

    def test_empty_missing_and_pin_count_fail(self):
        text = (".subckt leaf a b\n.ends\n"
                ".subckt top a b\nX1 a b leaf\nX2 a missing\n.ends\n")
        with TemporaryDirectory() as d:
            p = Path(d) / "test.spice"
            p.write_text(text)
            result = audit([p], "top")
            self.assertIn("leaf", result["empty"])
            self.assertIn("missing", result["missing"])

    def test_permuted_sram_ports_and_q_short_reported(self):
        original = (".subckt SP6TSRAM256x32 q[22] vss vdd\n.ends\n"
                    ".subckt top g p\nXram g g p SP6TSRAM256x32\n.ends\n")
        library = (".subckt SP6TSRAM256x32 vss vdd q[22]\n"
                   "M1 q[22] q[22] vss vss nmos\n.ends\n")
        with TemporaryDirectory() as d:
            top = Path(d) / "top.spice"
            model = Path(d) / "model.spice"
            top.write_text(original)
            model.write_text(library)
            result = audit([top, model], "top")
            self.assertEqual(result["port_order_mismatches"], [("sp6tsram256x32", 3, 3, True)])
            self.assertEqual(result["signals_on_supply"], [("Xram", "q[22]", "g")])

    def test_arity_and_duplicates_fail(self):
        top = ".subckt top a b\nX1 a child\n.ends\n"
        child = ".subckt child a b\nR1 a b 1k\n.ends\n"
        with TemporaryDirectory() as d:
            paths = [Path(d) / f"{i}.sp" for i in range(3)]
            for p, content in zip(paths, [top, child, child]):
                p.write_text(content)
            result = audit(paths, "top")
            self.assertTrue(result["bad_arity"])
            self.assertEqual(result["duplicate_implementations"], ["child"])

    def test_gzip_input(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "top.spice.gz"
            p.write_bytes(gzip.compress(b".subckt top a b\nR1 a b 1k\n.ends\n"))
            self.assertEqual(audit([p], "top")["top"].name, "top")


if __name__ == "__main__":
    unittest.main()
