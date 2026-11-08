"""Verspaeteter Lauf: GitHub startet den Bot oft Stunden zu spaet (06.11.2026: erster Lauf 13:36 New York).
Ein Ausbruch im Fenster 9:35 bis 10:35 muss trotzdem nach Regel gebucht werden, zur Zeit und zum Kurs des Signals."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_paper import DAY, START, Base, bar, chart, empty_state, paper  # noqa: E402

NEWS = {"flagged": [], "recent": 0}


def item(symbol, rv=2):
    return {"symbol": symbol, "rv": rv, "gap": 0.01, "atr": 2, "high": 11, "done": False}


def breakout(trigger, n, after=11.5, low=11.3):
    """Erstbalken mit Hoch 11, Schluss ueber 11 erst in Kerze `trigger`, danach `after`."""
    out = [bar(0, 10.5, 11, 10.4, 10.9, 1_000_000)]
    for i in range(1, n):
        if i < trigger:
            out.append(bar(i, 10.9, 10.98, 10.8, 10.95, 1_000_000))
        elif i == trigger:
            out.append(bar(i, 10.95, 11.45, 10.9, 11.4, 1_000_000))
        else:
            out.append(bar(i, after, max(after, 11.6), min(low, after), after, 1_000_000))
    return out


class LateRunTests(Base):
    def run_day(self, now, charts, symbols):
        os.environ["PAPER_NOW"] = f"{DAY} {now}"
        st = empty_state()
        st["inPlay"] = {"date": DAY, "scanned": len(symbols), "matches": len(symbols), "symbols": symbols}
        n = max(len(b) for b in charts.values())
        charts = dict(charts, SPY=[bar(i, 100, 110, 99, 100.5 + i * 0.1) for i in range(n)])
        with mock.patch.object(paper.data, "fetch", side_effect=lambda s, i, r: chart(charts[s])), \
                mock.patch.object(paper.strategy, "news_check", return_value=NEWS), \
                mock.patch.object(paper.strategy, "time_machine", return_value=None):
            paper.try_day(st, self.s, self.c)
            paper.manage(st, self.s, self.c)
        return st

    def test_late_start_books_breakout_at_signal(self):
        # Ausbruch in der Kerze 9:40 (Schluss 9:45), der Bot startet erst 11:30.
        st = self.run_day("11:30", {"X": breakout(2, 24)}, [item("X")])
        x = st["inPlay"]["symbols"][0]
        self.assertEqual(x["status"], "gekauft", x.get("why"))
        buy = st["accounts"]["day"]["journal"][0]
        self.assertEqual(buy["action"], "BUY")
        self.assertTrue(buy["late"])
        self.assertEqual(buy["timestamp"], f"{DAY}T09:45:00-05:00")
        self.assertEqual(buy["price"], round(11.4 * (1 + paper.cost(self.c)), 2))
        self.assertEqual(st["accounts"]["day"]["positions"][0]["openedAt"], f"{DAY}T09:45:00-05:00")
        self.assertNotIn("zu spaet", " ".join(d["detail"] for d in st.get("decisions", [])))

    def test_late_start_applies_stop_hit_since_signal(self):
        # Nach dem Ausbruch faellt der Kurs unter den Stop (Kerze 10:00); der Bot sieht das erst 11:30.
        st = self.run_day("11:30", {"X": breakout(2, 24, after=10.5, low=10.4)}, [item("X")])
        day = st["accounts"]["day"]
        self.assertEqual(day["positions"], [])
        sell = day["journal"][-1]
        self.assertEqual((sell["action"], sell["reason"]), ("SELL", "Stop"))
        self.assertEqual(sell["timestamp"], f"{DAY}T09:50:00-05:00")
        self.assertLess(sell["pnl"], 0)

    def test_late_breakouts_booked_in_time_order(self):
        st = self.run_day("11:30", {"A": breakout(6, 24), "B": breakout(2, 24)}, [item("A", rv=3), item("B")])
        buys = [j["symbol"] for j in st["accounts"]["day"]["journal"] if j["action"] == "BUY"]
        self.assertEqual(buys, ["B", "A"])

    def test_earlier_stop_counts_before_next_late_breakout(self):
        # A loest 9:40 aus und faellt 10:00 unter den Stop, B loest erst 10:25 aus. Bei B muss A schon verkauft sein,
        # sonst rechnen Risiko- und Geldpruefung mit einer Position, die ein puenktlicher Lauf nicht mehr gehabt haette.
        st = self.run_day("11:30", {"A": breakout(2, 24, after=10.88, low=10.85), "B": breakout(11, 24)},
                          [item("A", rv=3), item("B")])
        flow = [(j["action"], j["symbol"]) for j in st["accounts"]["day"]["journal"]]
        self.assertEqual(flow[:3], [("BUY", "A"), ("SELL", "A"), ("BUY", "B")])

    def test_on_time_run_unchanged(self):
        # Puenktlich: Ausbruch schliesst 9:45, Lauf 9:51 kauft zum letzten Schluss wie bisher, ohne Nachhol-Vermerk.
        st = self.run_day("09:51", {"X": breakout(2, 4)}, [item("X")])
        buy = st["accounts"]["day"]["journal"][0]
        self.assertNotIn("late", buy)
        self.assertEqual(buy["timestamp"], f"{DAY}T09:51:00-05:00")

    def test_no_breakout_still_sorted_out_after_window(self):
        st = self.run_day("11:30", {"X": breakout(30, 24)}, [item("X")])
        self.assertEqual(st["inPlay"]["symbols"][0]["why"], "Kein Ausbruch in der ersten Stunde")


if __name__ == "__main__":
    unittest.main()
