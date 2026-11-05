"""Tests der Statistik ohne Netz."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import research  # noqa: E402

DAYS = [f"2026-09-{d:02d}" for d in range(1, 31)] + [f"2026-10-{d:02d}" for d in range(1, 15)]


class WalkForwardTests(unittest.TestCase):
    def test_choice_uses_only_past_days(self):
        # Variante A ist nur in den Testtagen gut. Wer in die Zukunft schaut, wuerde sie waehlen.
        matrix = {"A": {d: 0.0 for d in DAYS}, "B": {d: 1.0 for d in DAYS}}
        for d in DAYS[20:26]:
            matrix["A"][d] = 100.0
        folds, oos = research.walk_forward(matrix, DAYS, train=20, test=6)
        self.assertEqual(folds[0]["chosen"], "B")
        self.assertEqual(oos[0][1], 1.0)
        for f in folds:
            self.assertLess(f["train"][1], f["test"][0])

    def test_oos_days_do_not_overlap(self):
        matrix = {"A": {d: 1.0 for d in DAYS}}
        _, oos = research.walk_forward(matrix, DAYS, train=20, test=6)
        days = [d for d, _ in oos]
        self.assertEqual(len(days), len(set(days)))


class BootstrapTests(unittest.TestCase):
    def test_deterministic_and_contains_mean(self):
        vals = [1, -2, 3, 0.5, -1, 2, 4, -3]
        a, b = research.bootstrap_ci(vals), research.bootstrap_ci(vals)
        self.assertEqual(a, b)
        self.assertLessEqual(a["low"], a["mean"])
        self.assertGreaterEqual(a["high"], a["mean"])

    def test_empty(self):
        self.assertIsNone(research.bootstrap_ci([]))


class RealityCheckTests(unittest.TestCase):
    def test_noise_is_not_significant(self):
        rng = random.Random(1)
        matrix = {str(k): {d: rng.gauss(0, 10) for d in DAYS} for k in range(30)}
        self.assertGreater(research.reality_check(matrix, DAYS, n=500)["p"], 0.05)

    def test_real_edge_is_significant(self):
        rng = random.Random(2)
        matrix = {str(k): {d: rng.gauss(0, 10) for d in DAYS} for k in range(30)}
        matrix["edge"] = {d: rng.gauss(15, 5) for d in DAYS}
        self.assertLess(research.reality_check(matrix, DAYS, n=500)["p"], 0.05)


class ConsistencyTests(unittest.TestCase):
    def test_day_results_pass_full_history(self):
        seen = []

        def fake(data, spy, v, d, alldays, dailies, c):
            seen.append(len(alldays))
            return []
        orig = research.b2.in_play
        research.b2.in_play = fake
        try:
            research.day_results({}, {}, DAYS[15:], DAYS, {}, research.BASE, {})
        finally:
            research.b2.in_play = orig
        self.assertTrue(all(n == len(DAYS) for n in seen))


if __name__ == "__main__":
    unittest.main()
