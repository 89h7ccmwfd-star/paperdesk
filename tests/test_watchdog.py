"""Wachhund ohne Netz."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import watchdog  # noqa: E402

S_OPEN = {"open": True}
STATE = {"updatedAt": "2026-11-06T10:00:00-05:00"}
T0 = 1793977200  # 2026-11-06 10:00 New York


class WatchdogTests(unittest.TestCase):
    def test_fresh(self):
        self.assertIsNone(watchdog.stale_minutes(STATE, S_OPEN, T0 + 10 * 60))

    def test_stale(self):
        self.assertEqual(watchdog.stale_minutes(STATE, S_OPEN, T0 + 40 * 60), 40)

    def test_closed_market_never_stale(self):
        self.assertIsNone(watchdog.stale_minutes(STATE, {"open": False}, T0 + 600 * 60))


if __name__ == "__main__":
    unittest.main()
