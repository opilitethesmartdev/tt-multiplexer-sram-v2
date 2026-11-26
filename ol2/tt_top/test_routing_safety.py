import unittest

from routing_safety import (blocked_by_macro, blocked_by_other_pin,
                            gate_escape_rects, placement_halo_strips,
                            restricted_macro_crossing, segment_rect)


class RoutingSafetyTests(unittest.TestCase):
    def test_boundary_via_enclosure_is_rejected(self):
        macro = (1016960, 6460160, 2150000, 6735000)
        via = (1827840, 6459780, 1828600, 6460540)
        self.assertTrue(blocked_by_macro(via, [macro], 600))
        self.assertFalse(blocked_by_macro((1827840, 6458000, 1828600, 6458500),
                                          [macro], 600))

    def test_power_gate_bad_strap_and_side_escape(self):
        bbox = (3988320, 250880, 4010720, 572320)
        power = (4000920, 250880, 4010720, 571120)
        control = (3988320, 571720, 4010720, 572320)
        pin_blockers = [("control", control)]
        bad = [segment_rect(4005820, 570920, 4005820, 573520, 800)]
        self.assertTrue(blocked_by_other_pin(bad, "vdpwr", pin_blockers, 600))
        routes = gate_escape_rects(power, bbox, 4018400, 574000, 800, 600, 10)
        self.assertEqual(len(routes), 1)
        self.assertFalse(blocked_by_other_pin(routes[0], "vdpwr", pin_blockers, 600))
        self.assertTrue(routes[0][0][0] < power[2])
        self.assertTrue(routes[0][0][2] > bbox[2])
        self.assertFalse(restricted_macro_crossing(routes[0], [bbox], {bbox: [power]}))
        self.assertTrue(restricted_macro_crossing(bad, [bbox], {bbox: [power]}))

    def test_gap_and_same_net(self):
        shape = (0, 0, 10, 10)
        self.assertFalse(blocked_by_other_pin([shape], "p", [("q", (11, 0, 20, 10))], 1))
        self.assertTrue(blocked_by_other_pin([shape], "p", [("q", (11, 0, 20, 10))], 2))
        self.assertFalse(blocked_by_other_pin([shape], "p", [("p", (0, 0, 10, 10))], 1))

    def test_no_escape_without_pin_at_side(self):
        self.assertEqual(gate_escape_rects((10, 10, 20, 30),
                                           (0, 0, 40, 40),
                                           50, 50, 4, 3, 1), [])

    def test_placement_halo(self):
        self.assertEqual(placement_halo_strips((10, 20, 30, 40), 2),
                         [(8, 18, 32, 20), (8, 40, 32, 42),
                          (8, 20, 10, 40), (30, 20, 32, 40)])
        with self.assertRaises(ValueError):
            placement_halo_strips((10, 20, 30, 40), 0)


if __name__ == "__main__":
    unittest.main()
