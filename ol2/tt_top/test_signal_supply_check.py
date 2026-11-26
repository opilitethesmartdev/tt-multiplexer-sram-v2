import unittest

from signal_supply_check import def_pin_nets, signal_supply_conflicts


class SignalSupplyTests(unittest.TestCase):
    def test_multiline_def_and_untouched_spice(self):
        design = ("NETS 1 ;\n- signal ( a A )\n  ( b B ) + USE SIGNAL ;\n"
                  "END NETS\n")
        conn = def_pin_nets(design)
        self.assertEqual(conn, {("a", "A"): "signal", ("b", "B"): "signal"})
        spice = ".subckt top p\nXa vgnd cell\nXb signal cell\n.ends\n"
        original = spice[:]
        self.assertEqual(signal_supply_conflicts(spice, "top", {"cell": ["A"]},
                                                 conn, {"vgnd"}),
                         [("a", "A", "vgnd", "signal")])
        self.assertEqual(spice, original)

    def test_intentional_ground_does_not_conflict(self):
        spice = ".subckt top p\nXa vgnd cell\n.ends\n"
        self.assertEqual(signal_supply_conflicts(spice, "top", {"cell": ["A"]},
                                                 {("a", "A"): "vgnd"}, {"vgnd"}), [])

    def test_truncated_or_bad_arity_is_rejected(self):
        with self.assertRaises(ValueError):
            def_pin_nets("NETS 1 ;\n- sig ( a A )")
        with self.assertRaises(ValueError):
            signal_supply_conflicts(".subckt top p\nXa vgnd cell\n.ends\n",
                                    "top", {"cell": ["A", "B"]}, {}, {"vgnd"})


if __name__ == "__main__":
    unittest.main()
