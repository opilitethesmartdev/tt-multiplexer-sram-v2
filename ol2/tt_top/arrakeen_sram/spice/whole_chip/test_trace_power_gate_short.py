import unittest

import klayout.db as db

from trace_power_gate_short import shared_root_components


def rect(x1, y1, x2, y2):
    return db.Region(db.Box(x1, y1, x2, y2))


class PowerGateWitnessTest(unittest.TestCase):
    def test_shared_root_metal(self):
        control, power = rect(0, 0, 10, 10), rect(20, 0, 30, 10)
        self.assertEqual(len(shared_root_components(rect(5, 2, 25, 8),
                                                    control, power)), 1)

    def test_separate_root_metal(self):
        control, power = rect(0, 0, 10, 10), rect(20, 0, 30, 10)
        root = rect(5, 2, 10, 8) + rect(20, 2, 25, 8)
        self.assertEqual(shared_root_components(root, control, power), [])

    def test_edge_contact_is_not_positive_area_overlap(self):
        control, power = rect(0, 0, 10, 10), rect(20, 0, 30, 10)
        self.assertEqual(shared_root_components(rect(10, 2, 20, 8),
                                                control, power), [])

    def test_macro_overlap_is_inconclusive(self):
        with self.assertRaises(ValueError):
            shared_root_components(rect(0, 0, 30, 10),
                                   rect(0, 0, 20, 10), rect(10, 0, 30, 10))


if __name__ == "__main__":
    unittest.main()
