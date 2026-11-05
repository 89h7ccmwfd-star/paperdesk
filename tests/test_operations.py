"""Betrieb und Daten: Kalender, Datenpruefung, Not-Aus. Ohne Netz."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paper  # noqa: E402
from test_paper import START, Base, bar, chart, empty_state  # noqa: E402


class CalendarTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("PAPER_NOW", None)

    def at(self, when):
        os.environ["PAPER_NOW"] = when
        return paper.session()

    def test_normal_day(self):
        s = self.at("2026-11-05 10:00")
        self.assertTrue(s["open"])
        self.assertEqual(paper.ny(s["end"]).strftime("%H:%M"), "16:00")

    def test_holiday_closed(self):
        self.assertFalse(self.at("2026-11-26 10:00")["trading"])

    def test_weekend_closed(self):
        self.assertFalse(self.at("2026-11-07 10:00")["open"])

    def test_early_close(self):
        s = self.at("2026-11-27 12:00")
        self.assertTrue(s["open"])
        self.assertEqual(paper.ny(s["end"]).strftime("%H:%M"), "13:00")
        self.assertEqual(paper.ny(s["flatBy"]).strftime("%H:%M"), "12:55")
        self.assertFalse(self.at("2026-11-27 13:30")["open"])

    def test_calendar_end_is_loud(self):
        with self.assertRaises(RuntimeError):
            self.at("2028-01-03 10:00")


class DataCheckTests(Base):
    def test_complete_data(self):
        bars = [bar(i, 10, 11, 9, 10) for i in range(5)]
        self.assertIsNone(paper.check_bars(bars, START, START + 30 * 60))

    def test_gap_found(self):
        bars = [bar(i, 10, 11, 9, 10) for i in (0, 1, 3, 4)]
        self.assertIn("fehlende", paper.check_bars(bars, START, START + 30 * 60))

    def test_stale_found(self):
        bars = [bar(i, 10, 11, 9, 10) for i in range(2)]
        self.assertIn("alt", paper.check_bars(bars, START, START + 30 * 60))

    def test_gap_blocks_entry(self):
        st = empty_state()
        st["inPlay"] = {"date": "2026-11-05", "scanned": 1, "matches": 1,
                        "symbols": [{"symbol": "X", "rv": 2, "gap": 0.01, "atr": 2, "high": 11, "done": False}]}
        spy = chart([bar(i, 100, 101, 99, 100.5) for i in range(6)])
        x = chart([bar(i, 10.5, 11.5, 10.4, 11.4) for i in (0, 1, 3, 4, 5)])
        with mock.patch.object(paper, "fetch", side_effect=lambda s, i, r: spy if s == "SPY" else x):
            paper.try_day(st, self.s, self.c)
        item = st["inPlay"]["symbols"][0]
        self.assertFalse(item["done"])
        self.assertIn("Daten unvollständig", item["why"])
        self.assertEqual(st["accounts"]["day"]["journal"], [])


class StateTests(Base):
    def test_valid_state(self):
        self.assertEqual(paper.validate_state(empty_state()), [])

    def test_negative_cash(self):
        st = empty_state()
        st["accounts"]["day"]["cash"] = -1
        self.assertTrue(paper.validate_state(st))

    def test_halt_stops_trading(self):
        st = empty_state()
        st["accounts"]["swing"]["positions"] = [{"symbol": "X", "qty": 0, "entry": 10, "stop": 9}]
        path = os.path.join(self.dir, "state.json")
        with open(path, "w") as f:
            json.dump(st, f)
        with mock.patch.object(paper, "STATE", path), mock.patch.object(paper, "fetch") as fetch:
            paper.tick(do_publish=False)
            fetch.assert_not_called()
        with open(path) as f:
            saved = json.load(f)
        self.assertIn("Not-Aus", saved["status"])
        self.assertTrue(saved["halt"]["reasons"])


if __name__ == "__main__":
    unittest.main()
