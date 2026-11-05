"""Kennzahlen mit von Hand gerechneten Werten."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analytics  # noqa: E402


def trade(day, sym, buy, sell, qty, pnl, risk=50, note=None, strategy="inplay-1"):
    return [{"timestamp": f"{day}T10:00:00-05:00", "action": "BUY", "symbol": sym, "qty": qty, "price": buy, "fee": 1,
             "plannedRisk": risk, "strategy": strategy, **({"note": note} if note else {})},
            {"timestamp": f"{day}T15:00:00-05:00", "action": "SELL", "symbol": sym, "qty": qty, "price": sell, "fee": 1,
             "pnl": pnl}]


JOURNAL = (trade("2026-11-02", "A", 100, 102, 10, 18) + trade("2026-11-03", "B", 50, 49, 20, -22)
           + trade("2026-11-04", "C", 20, 21, 50, 48))


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.m = analytics.metrics(JOURNAL, 10000)

    def test_basic(self):
        m = self.m
        self.assertEqual(m["trades"], 3)
        self.assertEqual(m["netPnl"], 44)
        self.assertAlmostEqual(m["winRate"], 2 / 3, places=4)
        self.assertEqual(m["avgWin"], 33)
        self.assertEqual(m["avgLoss"], -22)
        self.assertEqual(m["profitFactor"], round(66 / 22, 3))
        self.assertEqual(m["expectancy"], round(44 / 3, 2))
        self.assertEqual(m["avgHoldMin"], 300)
        self.assertEqual(m["fees"], 6)

    def test_drawdown_and_recovery(self):
        self.assertEqual(self.m["maxDrawdown"], -22)
        self.assertEqual(self.m["recoveryFactor"], round(44 / 22, 2))

    def test_sharpe(self):
        r = [18 / 10000, -22 / 10018, 48 / 9996]
        mu = sum(r) / 3
        sd = math.sqrt(sum((x - mu) ** 2 for x in r) / 2)
        self.assertAlmostEqual(self.m["sharpe"], round(mu / sd * math.sqrt(252), 2))

    def test_excludes_marked_trades(self):
        j = JOURNAL + trade("2026-11-05", "X", 10, 9, 10, -12, note="Fehlbuchung")
        self.assertEqual(analytics.metrics(j, 10000)["trades"], 3)
        self.assertEqual(analytics.metrics(j, 10000, exclude_notes=False)["trades"], 4)

    def test_empty_and_single(self):
        self.assertEqual(analytics.metrics([], 10000), {"trades": 0, "strategy": "alle"})
        one = analytics.metrics(trade("2026-11-02", "A", 100, 102, 10, 18), 10000)
        self.assertIsNone(one["sharpe"])
        self.assertIsNone(one["profitFactor"])

    def test_by_strategy(self):
        j = JOURNAL + trade("2026-11-05", "D", 10, 11, 10, 8, strategy="inplay-2")
        rep = analytics.report({"accounts": {"day": {"journal": j, "startingCash": 10000}}, "orders": []})
        self.assertEqual(rep["day"]["byStrategy"]["inplay-1"]["trades"], 3)
        self.assertEqual(rep["day"]["byStrategy"]["inplay-2"]["trades"], 1)


if __name__ == "__main__":
    unittest.main()
