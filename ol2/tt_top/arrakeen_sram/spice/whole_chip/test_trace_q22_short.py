#!/usr/bin/env python3
"""Small independent synthetic tests for the GDS geometry witness."""
import unittest

import klayout.db as db

from trace_q22_short import LAYERS, path_between


def rectangle(x1, y1, x2, y2):
    return db.Region(db.Box(x1, y1, x2, y2))


class TraceTest(unittest.TestCase):
    def setUp(self):
        self.regions = {name: db.Region() for name in LAYERS}
        self.regions["m3"] = rectangle(0, 0, 20, 20)
        self.regions["v2"] = rectangle(10, 10, 15, 15)
        self.regions["m2"] = rectangle(10, 10, 20, 20)
        self.regions["v1"] = rectangle(11, 11, 14, 14)
        self.regions["m1"] = rectangle(10, 10, 20, 20)
        self.q = rectangle(1, 1, 2, 2)
        self.ground = rectangle(16, 16, 17, 17)

    def test_positive_overlap_path(self):
        path = path_between(self.regions, self.q, self.ground)
        self.assertEqual([layer for layer, _ in path],
                         ["m3", "v2", "m2", "v1", "m1"])

    def test_missing_via_does_not_connect(self):
        self.regions["v1"] = db.Region()
        self.assertIsNone(path_between(self.regions, self.q, self.ground))

    def test_edge_only_via_contact_does_not_connect(self):
        self.regions["v1"] = rectangle(20, 10, 25, 15)
        self.assertIsNone(path_between(self.regions, self.q, self.ground))

    def test_missing_probe_fails_closed(self):
        with self.assertRaises(ValueError):
            path_between(self.regions, rectangle(100, 100, 101, 101), self.ground)


if __name__ == "__main__":
    unittest.main()
