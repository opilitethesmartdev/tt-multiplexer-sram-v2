import unittest

import klayout.db as db
from check_gate_gds import root_bridges


def box(x0, y0, x1, y1):
    return db.Region(db.Box(x0, y0, x1, y1))


class GateGdsCheckTest(unittest.TestCase):
    def test_bridge(self):
        self.assertEqual(len(root_bridges(box(2, 0, 28, 10),
                                         box(0, 0, 10, 10),
                                         box(20, 0, 30, 10))), 1)

    def test_no_bridge(self):
        root = (box(2, 0, 9, 10) + box(21, 0, 28, 10)).merged()
        self.assertEqual(root_bridges(root, box(0, 0, 10, 10),
                                      box(20, 0, 30, 10)), [])

    def test_edge_touch_does_not_count(self):
        self.assertEqual(root_bridges(box(10, 0, 20, 10),
                                      box(0, 0, 10, 10),
                                      box(20, 0, 30, 10)), [])


if __name__ == "__main__":
    unittest.main()
