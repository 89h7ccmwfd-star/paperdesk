#!/usr/bin/env python3
"""Andere Ansaetze statt Feintuning, mit Vergleich zu Kaufen und Halten. Gleiche Kosten und Aufteilung wie backtest.py."""
import itertools
import json
import os
import sys
import time

import backtest as bt
import paper

SLIP = bt.SLIP
RISK = 50.0
MAX_POS = 3000.0


def daily(d, days):
    """Tageskerzen aus den 5-Minuten-Kerzen."""
    out = {}
    for x in days:
        if x in d:
            b = d[x]
            out[x] = {"o": b[0]["o"], "h": max(y["h"] for y in b), "l": min(y["l"] for y in b), "c": b[-1]["c"],
                      "first": b[0]["v"]}
    return out


def atr(dd, days, n=14):
    trs = []
    for a, b in zip(days[-n - 1:-1], days[-n:]):
        trs.append(max(dd[b]["h"] - dd[b]["l"], abs(dd[b]["h"] - dd[a]["c"]), abs(dd[b]["l"] - dd[a]["c"])))
    return sum(trs) / n


def market_ok(spy, day, i):
    b = spy.get(day)
    if not b or i >= len(b):
        return False
    return b[i]["c"] > b[0]["o"]


def in_play(data, spy, v, day, alldays, dailies):
    """Aktien mit ungewoehnlich viel Volumen im ersten Balken, Ausbruch nach dem ersten Balken."""
    ranked = []
    idx = alldays.index(day)
    if idx < 15:
        return []
    for s, d in data.items():
        if day not in d or len(d[day]) < 2:
            continue
        hist = [x for x in alldays[idx - 15:idx] if x in d]
        if len(hist) < 15:
            continue
        first = d[day][0]
        avg = sum(dailies[s][x]["first"] for x in hist[-14:]) / 14
        rv = first["v"] / avg if avg else 0
        gap = first["o"] / dailies[s][hist[-1]]["c"] - 1
        if rv < v["rv"] or first["c"] <= first["o"] or gap < v["gap"]:
            continue
        ranked.append((rv, s, atr(dailies[s], hist)))
    ranked.sort(reverse=True)
    trades = []
    for rv, s, a in ranked[:v["top"]]:
        bars = d = data[s][day]
        high = bars[0]["h"]
        for i in range(1, min(len(bars) - 1, 1 + v["window"])):
            if bars[i]["c"] <= high:
                continue
            if v["mkt"] and not market_ok(spy, day, i):
                break
            # "next": realistischer, Kauf erst zum Eroeffnungskurs des naechsten Balkens.
            entry = (bars[i + 1]["o"] if v.get("next") else bars[i]["c"]) * (1 + SLIP)
            stop = entry - v["atr"] * a
            if stop <= 0:
                break
            qty = int(min(RISK / (entry - stop), MAX_POS / entry))
            if qty < 1:
                break
            target = entry + v["r"] * (entry - stop) if v["r"] else None
            px = None
            for x in bars[i + 1:]:
                if x["l"] <= stop:
                    px = min(x["o"], stop)
                    break
                if target and x["h"] >= target:
                    px = target
                    break
            if px is None:
                px = bars[-1]["c"]
            px *= 1 - SLIP
            pnl = (px - entry) * qty - paper.fee(qty) * 2
            trades.append({"i": i, "pnl": pnl, "r": pnl / (RISK), "s": s})
            break
    trades.sort(key=lambda t: t["i"])
    return trades[:v["max"]]


def summarize(results):
    rs = [t["r"] for x in results for t in x]
    pnl = sum(t["pnl"] for x in results for t in x)
    curve = peak = dd = 0.0
    for x in results:
        curve += sum(t["pnl"] for t in x)
        peak = max(peak, curve)
        dd = min(dd, curve - peak)
    return {"pnl": round(pnl), "trades": len(rs), "win": round(sum(r > 0 for r in rs) / len(rs), 3) if rs else 0,
            "avgR": round(sum(rs) / len(rs), 3) if rs else 0, "maxDD": round(dd)}


def buy_hold(series, days):
    a, b = series[days[0]], series[days[-1]]
    return round((b[-1]["c"] / a[0]["o"] - 1) * 100, 2)


def swing_test(symbols):
    """Aktuelle Swing-Regel ueber 2 Jahre Tageskerzen."""
    data = {}
    for s in symbols:
        p = os.path.join(bt.CACHE, "d_" + s + ".json")
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < 86400:
            data[s] = json.load(open(p))
            continue
        try:
            bars = paper.rows(paper.fetch(s, "1d", "2y"), bar=86400)
        except Exception:
            continue
        json.dump(bars, open(p, "w"))
        data[s] = bars
        time.sleep(0.1)
    trades = []
    for s, bars in data.items():
        i, open_until = 50, 0
        while i < len(bars) - 1:
            c = [b["c"] for b in bars[:i + 1]]
            sma20, sma50 = sum(c[-20:]) / 20, sum(c[-50:]) / 50
            hit = None
            if c[-1] > max(c[-21:-1]):
                hit = "breakout_20d"
            elif c[-6] / c[-16] > 1.10 and max(c[-5:]) / min(c[-5:]) < 1.05:
                hit = "bull_flag"
            elif c[-2] < sum(c[-21:-1]) / 20 and c[-1] > sma20:
                hit = "reclaim_ma20"
            if not hit or not c[-1] > sma20 > sma50:
                i += 1
                continue
            entry = bars[i + 1]["o"] * (1 + SLIP)
            stop = min(b["l"] for b in bars[i - 9:i + 1])
            risk = entry - stop
            if risk <= 0 or risk / entry > 0.08:
                i += 1
                continue
            target = entry + 2 * risk
            px, j = None, i + 1
            for j in range(i + 1, min(i + 41, len(bars))):
                if bars[j]["l"] <= stop:
                    px = min(bars[j]["o"], stop)
                    break
                if bars[j]["h"] >= target:
                    px = target
                    break
            if px is None:
                px = bars[j]["c"]
            trades.append({"setup": hit, "t": bars[i]["t"], "r": (px * (1 - SLIP) - entry) / risk})
            i = j + 1
    trades.sort(key=lambda t: t["t"])
    out = {}
    for name in ("breakout_20d", "bull_flag", "reclaim_ma20"):
        rs = [t["r"] for t in trades if t["setup"] == name]
        half = len(rs) // 2
        out[name] = {"trades": len(rs), "avgR": round(sum(rs) / max(len(rs), 1), 3),
                     "first": round(sum(rs[:half]) / max(half, 1), 3),
                     "second": round(sum(rs[half:]) / max(len(rs) - half, 1), 3)}
    return out


def current():
    """Aktuelle Parameter mit vorsichtigen Annahmen (Kauf zum naechsten Open, doppelte Slippage); fuers Dashboard."""
    global SLIP
    SLIP = 0.0004
    c = paper.cfg()
    v = {"rv": c["rv"], "gap": c["gap"], "top": int(c["top"]), "atr": c["atr"], "r": 0, "mkt": True,
         "window": int(c["window"]), "max": int(c["max_day_trades"]), "next": True}
    data = bt.load_all(paper.UNIVERSE)
    spy = bt.load_all(["SPY"])["SPY"]
    days = sorted(x for x in {d for w in data.values() for d in w} if x < paper.ny().date().isoformat())
    dailies = {s: daily(d, days) for s, d in data.items()}
    t = days[15:]
    mid = len(t) // 2
    a = [in_play(data, spy, v, d, days, dailies) for d in t[:mid]]
    b = [in_play(data, spy, v, d, days, dailies) for d in t[mid:]]
    out = {"at": paper.iso(), "from": t[0], "to": t[-1], "days": len(t), "first": summarize(a), "second": summarize(b),
           "all": summarize(a + b), "spyPct": buy_hold(spy, t), "oldRulePnl": -1592, "oldRuleTrades": 177}
    with open(os.path.join(paper.HOME, "site", "backtest.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out))


def main():
    data = bt.load_all(paper.UNIVERSE)
    spy_all = bt.load_all(["SPY"])["SPY"]
    days = sorted(x for x in {d for v in data.values() for d in v} if x < paper.ny().date().isoformat())
    dailies = {s: daily(d, days) for s, d in data.items()}
    tradable = days[15:]
    mid = len(tradable) // 2
    a, b = tradable[:mid], tradable[mid:]
    print("Testtage", len(tradable), a[0], a[-1], "|", b[0], b[-1])
    print("Kaufen und Halten SPY %:", buy_hold(spy_all, a), buy_hold(spy_all, b), "gesamt", buy_hold(spy_all, tradable))
    ew = []
    for s, d in data.items():
        if tradable[0] in d and tradable[-1] in d:
            ew.append(buy_hold(d, tradable))
    print("Gleichgewichtet 98 Aktien % (Liste von heute, schoent):", round(sum(ew) / len(ew), 2))
    rows = []
    grid = itertools.product([1.0, 1.5, 2.5], [0.0, 0.005], [5, 20], [0.1, 0.25, 0.5], [0, 2.0], [False, True], [12, 77])
    for rv, gap, top, at, r, mkt, window in grid:
        v = {"rv": rv, "gap": gap, "top": top, "atr": at, "r": r, "mkt": mkt, "window": window, "max": 3}
        ra = [in_play(data, spy_all, v, d, days, dailies) for d in a]
        rb = [in_play(data, spy_all, v, d, days, dailies) for d in b]
        rows.append((v, summarize(ra), summarize(rb)))
    good = [x for x in rows if x[1]["trades"] >= 25 and x[2]["trades"] >= 25]
    pos = [x for x in good if x[1]["pnl"] > 0 and x[2]["pnl"] > 0]
    print(f"In-Play: {len(rows)} Varianten, {len(good)} mit genug Trades, in beiden Haelften positiv: {len(pos)}")
    good.sort(key=lambda x: -min(x[1]["avgR"], x[2]["avgR"]))
    for v, x, y in good[:10]:
        print({k: v[k] for k in ("rv", "gap", "top", "atr", "r", "mkt", "window")}, x, y)
    print("Median avgR Haelfte 2:", sorted(x[2]["avgR"] for x in good)[len(good) // 2] if good else None)
    print("Swing aktuell:", json.dumps(swing_test(paper.UNIVERSE)))
    json.dump(rows, open(os.path.join(bt.CACHE, "_grid2.json"), "w"))


if __name__ == "__main__":
    current() if "current" in sys.argv else main()
