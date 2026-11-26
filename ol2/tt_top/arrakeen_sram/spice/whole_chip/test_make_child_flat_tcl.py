from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import gdstk
from make_child_flat_tcl import generate


class ChildFlatTests(unittest.TestCase):
    def write_gds(self, path, extra_top=False, child_name="child"):
        library = gdstk.Library()
        child = library.new_cell(child_name)
        child.add(gdstk.rectangle((0, 0), (1, 1)))
        root = library.new_cell("tt_gf_wrapper")
        root.add(gdstk.Reference(child))
        if extra_top:
            library.new_cell("other_top")
        library.write_gds(str(path))

    def test_flattens_child_not_top(self):
        with TemporaryDirectory() as d:
            gds = Path(d) / "chip.gds"
            self.write_gds(gds)
            text, count = generate(gds, "/tmp/chip.gds", "tt_gf_wrapper", "result.spice")
            self.assertEqual(count, 1)
            self.assertIn("gds flatglob {child}", text)
            self.assertNotIn("gds flatglob {tt_gf_wrapper}", text)
            self.assertIn("load {tt_gf_wrapper}", text)

    def test_rejects_ambiguous_top_and_globs(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "chip.gds"
            self.write_gds(p, extra_top=True)
            with self.assertRaises(ValueError):
                generate(p, "/tmp/chip.gds", "tt_gf_wrapper", "result.spice")
            p2 = Path(d) / "special.gds"
            self.write_gds(p2, child_name="cell*")
            with self.assertRaises(ValueError):
                generate(p2, "/tmp/chip.gds", "tt_gf_wrapper", "result.spice")


if __name__ == "__main__":
    unittest.main()
