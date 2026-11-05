"""Tests ohne Netz: python3 -m unittest discover -s tests"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest2  # noqa: E402
import paper  # noqa: E402

DAY = "2026-11-05"
START = int(dt.datetime.fromisoformat(DAY + "T09:30").replace(tzinfo=paper.NY).timestamp())


def bar(i, o, h, l, c, v=1000):
    return {"t": START + i * paper.BAR, "o": o, "h": h, "l": l, "c": c, "v": v}


def chart(bars):
    """Yahoo-Antwort aus Kerzen bauen."""
    return {"meta": {}, "timestamp": [b["t"] for b in bars],
            "indicators": {"quote": [{k: [b[x] for b in bars] for k, x in
                                      (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v"))}]}}


def empty_state():
    acc = {"startingCash": 10000, "cash": 10000, "equity": 10000, "realizedPnl": 0, "positions": [], "journal": []}
    return {"accounts": {"day": json.loads(json.dumps(acc)), "swing": json.loads(json.dumps(acc))}}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ["PAPER_NOW"] = DAY + " 10:00"
        self.c = dict(paper.DEFAULTS, max_risk=250.0, max_position=5000.0, max_day_loss=500.0)
        self.s = {"start": START, "end": START + 23400, "open": True, "noEntryBefore": START + 300,
                  "swingAfter": START + 900, "noEntryAfter": START + 21600, "flatBy": START + 23100}

    def tearDown(self):
        os.environ.pop("PAPER_NOW", None)
        shutil.rmtree(self.dir)


class DataTests(Base):
    def test_bad_bars_dropped(self):
        bars = [bar(0, 10, 11, 9, 10), bar(0, 10, 11, 9, 10), bar(1, 10, 9, 11, 10), bar(2, 10, 11, 9, 10.5)]
        out = paper.rows(chart(bars))
        self.assertEqual([b["t"] for b in out], [START, START + 600])

    def test_open_bar_not_used(self):
        os.environ["PAPER_NOW"] = DAY + " 09:37"
        out = paper.rows(chart([bar(0, 10, 11, 9, 10), bar(1, 10, 11, 9, 10)]))
        self.assertEqual(len(out), 1)

    def test_first_bar_must_be_open(self):
        self.assertIsNone(paper.first_bar([bar(1, 10, 11, 9, 10)], START))
        self.assertIsNotNone(paper.first_bar([bar(0, 10, 11, 9, 10)], START))

    def test_trigger_uses_time_index(self):
        # Balken 2 fehlt: Ausloeser ist Balken 3, und nach Balken 12 zaehlt nichts mehr.
        bars = [bar(0, 10, 11, 9, 10.5), bar(1, 10, 10.9, 9.5, 10.8), bar(3, 10.8, 11.2, 10.7, 11.1)]
        self.assertEqual(paper.find_trigger(bars, 11, START, 12), 2)
        late = [bar(0, 10, 11, 9, 10.5), bar(13, 10.8, 11.3, 10.7, 11.2)]
        self.assertIsNone(paper.find_trigger(late, 11, START, 12))


class ConfigTests(Base):
    def test_config_validation(self):
        for bad in ({"max_risk": -5}, {"tipfehler": 1}, {"slippage": "0.1"}, {"max_day_trades": True}):
            path = os.path.join(self.dir, "config.json")
            with open(path, "w") as f:
                json.dump(bad, f)
            with mock.patch.object(paper, "CONFIG", path), self.assertRaises(SystemExit):
                paper.cfg()


class RiskTests(Base):
    def test_plan_size(self):
        p, _ = paper.plan(100.0, 4.0, self.c)
        self.assertEqual(p["stop"], 99.0)
        self.assertEqual(p["qty"], 50)  # 5.000 $ Positionsgrenze vor 250 $ Risiko
        self.assertLessEqual(p["plannedRisk"], self.c["max_risk"])

    def test_day_loss_counts_open_risk(self):
        st = empty_state()
        st["accounts"]["day"]["positions"] = [{"symbol": "X", "qty": 100, "entry": 50, "stop": 46, "last": 47}]
        why = paper.risk_block(st, "day", "Y", 100, 20, 18.5, None, 20, self.s, self.c)
        self.assertIn("Tagesverlustgrenze", why or "")

    def test_day_loss_closes_positions(self):
        st = empty_state()
        acc = st["accounts"]["day"]
        acc["cash"] = 5000
        acc["positions"] = [{"symbol": "X", "qty": 100, "entry": 50, "stop": 40, "target": None, "entryFee": 1,
                             "openedAt": paper.iso(START + 600), "last": 50}]
        with mock.patch.object(paper, "fetch", return_value=chart([bar(5, 45, 45.5, 44, 44.5)])):
            paper.manage(st, self.s, self.c)
        self.assertEqual(acc["positions"], [])
        self.assertEqual(acc["journal"][-1]["reason"], "Tagesverlustgrenze erreicht")


class ExecutionTests(Base):
    def test_stop_in_entry_bar(self):
        st = empty_state()
        acc = st["accounts"]["day"]
        acc["positions"] = [{"symbol": "X", "qty": 10, "entry": 100, "stop": 99, "target": None, "entryFee": 1,
                             "openedAt": paper.iso(START + 11 * 60), "last": 100}]
        with mock.patch.object(paper, "fetch", return_value=chart([bar(2, 100, 100.2, 98.5, 99.4)])):
            paper.manage(st, self.s, self.c)
        self.assertEqual(acc["journal"][-1]["reason"], "Stop")

    def test_slippage_applied(self):
        st = empty_state()
        pos = {"symbol": "X", "qty": 10, "entry": 100, "stop": 99, "target": None, "entryFee": 1, "last": 100}
        st["accounts"]["day"]["positions"] = [pos]
        paper.sell(st, "day", pos, 100.0, "Test", 0.001)
        self.assertEqual(st["accounts"]["day"]["journal"][-1]["price"], 99.9)

    def test_tick_survives_data_error(self):
        st = empty_state()
        st["inPlay"] = {"date": DAY, "scanned": 1, "matches": 1,
                        "symbols": [{"symbol": "X", "rv": 2, "gap": 0.01, "atr": 2, "high": 11, "done": False}]}
        spy = chart([bar(i, 100, 101, 99, 100.5) for i in range(5)])

        def fetch(symbol, interval, range_):
            if symbol == "SPY":
                return spy
            raise RuntimeError("Yahoo antwortet nicht")
        with mock.patch.object(paper, "fetch", side_effect=fetch):
            paper.try_day(st, self.s, self.c)
        self.assertEqual(st["errors"][-1]["where"], "X")
        self.assertFalse(st["inPlay"]["symbols"][0]["done"])


class OrderTests(Base):
    def test_volume_cap_partial_fill(self):
        self.assertEqual(paper.fill_qty(500, 20_000, self.c), 200)
        self.assertEqual(paper.fill_qty(50, 20_000, self.c), 50)
        self.assertEqual(paper.fill_qty(50, 50, self.c), 0)

    def test_cost_includes_half_spread(self):
        self.assertAlmostEqual(paper.cost(self.c), self.c["spread"] / 2 + self.c["slippage"])

    def test_sell_records_order(self):
        st = empty_state()
        pos = {"symbol": "X", "qty": 10, "entry": 100, "stop": 99, "target": None, "entryFee": 1, "last": 100}
        st["accounts"]["day"]["positions"] = [pos]
        paper.sell(st, "day", pos, 99.0, "Stop", 0.001)
        o = st["orders"][-1]
        self.assertEqual((o["type"], o["status"], o["filledQty"]), ("stop", "filled", 10))
        self.assertAlmostEqual(o["refPrice"] - o["fillPrice"], o["costPerShare"])

    def test_low_volume_rejects_buy(self):
        st = empty_state()
        st["inPlay"] = {"date": "2026-11-05", "scanned": 1, "matches": 1,
                        "symbols": [{"symbol": "X", "rv": 2, "gap": 0.01, "atr": 2, "high": 11, "done": False}]}
        spy = chart([bar(i, 100, 110, 99, 100.5 + i) for i in range(6)])
        x = chart([bar(i, 10.5, 10.95 if i else 11, 10.4, 10.9, 10) for i in range(5)] + [bar(5, 10.9, 11.5, 10.8, 11.4, 10)])
        with mock.patch.object(paper, "fetch", side_effect=lambda s, i, r: spy if s == "SPY" else x):
            paper.try_day(st, self.s, self.c)
        self.assertEqual(st["orders"][-1]["status"], "rejected")
        self.assertEqual(st["accounts"]["day"]["positions"], [])


class ParityTests(Base):
    def test_backtest_uses_live_rules(self):
        days = [f"2026-10-{d:02d}" for d in range(1, 16)] + [DAY]
        first = {d: 1000 for d in days}
        dailies = {s: {d: {"o": 100, "h": 101, "l": 99, "c": 100, "first": first[d]} for d in days} for s in "ABC"}
        today = [bar(0, 101, 102, 100.5, 101.8, 5_000_000), bar(1, 101.8, 102.5, 101.7, 102.4, 3_000_000)]
        today += [bar(i, 102.4, 102.6, 102.2, 102.5, 2_000_000) for i in range(2, 78)]
        data = {s: {**{d: [] for d in days[:-1]}, DAY: today} for s in "ABC"}
        spy = {DAY: [bar(i, 400, 401, 399, 400.5 + i * 0.01) for i in range(78)]}
        v = {"rv": 1.0, "gap": 0.005, "top": 5, "atr": 0.25, "r": 0, "mkt": True, "window": 12, "max": 3, "next": True}
        trades = backtest2.in_play(data, spy, v, DAY, days, dailies, self.c)
        live, _ = paper.plan(102.4 * (1 + paper.cost(self.c)), backtest2.atr(dailies["A"], days[:15]),
                             dict(self.c, atr=0.25))
        self.assertTrue(trades)
        self.assertAlmostEqual(trades[0]["risk"], live["plannedRisk"])
        # Gemeinsame Kasse: drei Kandidaten zu je knapp 5.000 $, nur zwei passen in 10.000 $.
        self.assertLessEqual(sum(t["cost"] for t in trades), 10000)
        self.assertEqual(len(trades), 2)


if __name__ == "__main__":
    unittest.main()
