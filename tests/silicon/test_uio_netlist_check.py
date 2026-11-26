"""Test the fail-closed netlist check without importing the LibreLane stack."""
import ast
from pathlib import Path
import re
import unittest


BUILD = Path(__file__).resolve().parents[2] / "ol2" / "tt_top" / "build.py"
tree = ast.parse(BUILD.read_text(encoding="utf8"))
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
           and n.name == "CheckUioTristates")
method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
              and n.name == "check")
method.decorator_list = []
scope = {"re": re}
exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
             str(BUILD), "exec"), scope)
check = scope["check"]


def netlist():
    pins = ", ".join(f"en[{i}]" for i in reversed(range(8)))
    text = f"tt_ctrl ctrl (.pad_uio_oex({{{pins}}}));\n"
    for i in range(8):
        text += (f"gf180mcu_fd_sc_mcu7t5v0__bufz_12 buf{i} "
                 f"(.I(data[{i}]), .EN(en[{i}]), .Z(pad_raw[{37+i}]));\n")
    return text


class TestCheck(unittest.TestCase):
    def test_valid(self):
        check(netlist())

    def test_missing_buffer(self):
        with self.assertRaises(ValueError):
            check(netlist().replace(".Z(pad_raw[37])", ".Z(disconnected)"))

    def test_wrong_enable(self):
        with self.assertRaises(ValueError):
            check(netlist().replace(".EN(en[0])", ".EN(en[1])"))

    def test_constant_enable(self):
        with self.assertRaises(ValueError):
            check(netlist().replace(".EN(en[0])", ".EN(1'b1)"))

    def test_missing_controller(self):
        with self.assertRaises(ValueError):
            check(netlist().replace(".pad_uio_oex", ".not_the_enable"))

    def test_vector_enable(self):
        pins = ", ".join(f"en[{i}]" for i in reversed(range(8)))
        check(netlist().replace(f"{{{pins}}}", "en"))


if __name__ == "__main__":
    unittest.main()
