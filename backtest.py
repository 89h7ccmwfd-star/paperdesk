#!/usr/bin/env python3
"""Rueckblick ueber bis zu 60 Handelstage (5-Minuten-Kerzen von Yahoo), ohne Blick in die Zukunft.

Erste Haelfte der Tage zum Auswaehlen, zweite Haelfte zum Pruefen: Nur was in beiden traegt, zaehlt.
Kosten: Gebuehr aus paper.fee plus Slippage je Seite.
Bekannte Grenze: Die Aktienliste ist von heute (Survivorship Bias), News-Filter nicht rueckwirkend pruefbar.
"""
import itertools
import json
import os
import sys
import time

import paper

CACHE = os.path.join(paper.HOME, "cache")
SLIP = 0.0002
RISK = 50.0


def load_all(symbols):
    os.makedirs(CACHE, exist_ok=True)
    out = {}
    for s in symbols:
        p = os.path.join(CACHE, s + ".json")
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < 86400:
            with open(p) as f:
                out[s] = json.load(f)
            continue
        try:
            days = {}
            for b in paper.session_bars(paper.fetch(s, "5m", "60d")):
                days.setdefault(paper.ny(b["t"]).date().isoformat(), []).append(b)
            days = {d: x for d, x in days.items() if len(x) >= 70}
            with open(p, "w") as f:
                json.dump(days, f)
            out[s] = days
        except Exception as e:
            print("skip", s, e, file=sys.stderr)
        time.sleep(0.1)
    return out


def trade(bars, v):
    """Ein Ausbruch je Aktie und Tag. Liefert Einstiegsindex und Ergebnis in USD."""
    n = v["or"] * 60 // paper.BAR
    if len(bars) <= n + 1:
        return None
    rng = bars[:n]
    high, low = max(b["h"] for b in rng), min(b["l"] for b in rng)
    avg = sum(b["v"] for b in rng) / n
    vwap_num = sum((b["h"] + b["l"] + b["c"]) / 3 * b["v"] for b in rng)
    vwap_den = sum(b["v"] for b in rng)
    for i in range(n, len(bars) - 1):
        b = bars[i]
        vwap_num += (b["h"] + b["l"] + b["c"]) / 3 * b["v"]
        vwap_den += b["v"]
        if i - n >= v["window"]:
            return None
        if b["c"] <= high:
            continue
        if b["v"] < v["vol"] * avg:
            return None
        if v["vwap"] and b["c"] <= vwap_num / max(vwap_den, 1):
            return None
        entry = b["c"] * (1 + SLIP)
        stop = (high + low) / 2 if v["stop"] == "mid" else low
        risk = entry - stop
        if risk <= 0 or risk / entry < v["minrisk"]:
            return None
        qty = int(RISK / risk)
        if qty < 1 or qty * entry > 9000:
            return None
        target = entry + v["r"] * risk if v["r"] else None
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
        px *= (1 - SLIP)
        pnl = (px - entry) * qty - paper.fee(qty) * 2
        return {"i": i, "pnl": pnl, "r": pnl / (risk * qty), "cost": qty * entry}
    return None


def run(data, v, days):
    """Tagesdepot: hoechstens max_trades je Tag, frueheste Ausbrueche zuerst, Filter ohne Zukunftswissen."""
    results = []
    for day in days:
        cand = []
        for s, d in data.items():
            if day not in d:
                continue
            if v["trend"]:
                prev = [x for x in sorted(d) if x < day][-20:]
                if len(prev) < 20:
                    continue
                closes = [d[x][-1]["c"] for x in prev]
                if d[day][0]["o"] < sum(closes) / 20:
                    continue
            t = trade(d[day], v)
            if t:
                cand.append(t)
        cand.sort(key=lambda t: t["i"])
        results.append(sum(t["pnl"] for t in cand[:v["max"]]))
        results[-1] = {"pnl": results[-1], "trades": [t["r"] for t in cand[:v["max"]]]}
    rs = [r for x in results for r in x["trades"]]
    pnl = sum(x["pnl"] for x in results)
    curve = peak = dd = 0.0
    for x in results:
        curve += x["pnl"]
        peak = max(peak, curve)
        dd = min(dd, curve - peak)
    return {"pnl": round(pnl), "trades": len(rs), "win": round(sum(r > 0 for r in rs) / len(rs), 3) if rs else 0,
            "avgR": round(sum(rs) / len(rs), 3) if rs else 0, "maxDD": round(dd)}


def main():
    data = load_all(paper.UNIVERSE)
    days = sorted({d for x in data.values() for d in x})
    today = paper.ny().date().isoformat()
    days = [d for d in days if d < today]
    mid = len(days) // 2
    a, b = days[:mid], days[mid:]
    print(f"{len(data)} Aktien, {len(days)} Tage: {a[0]}..{a[-1]} | {b[0]}..{b[-1]}")
    grid = itertools.product([15, 30], ["mid", "low"], [1.0, 1.5, 2.0, 3.0, 0], [0.0, 1.0, 1.5], [False, True],
                             [False, True], [12, 24, 69], [3])
    rows = []
    for orm, stop, r, vol, vwap, trend, window, mx in grid:
        v = {"or": orm, "stop": stop, "r": r, "vol": vol, "vwap": vwap, "trend": trend, "window": window,
             "max": mx, "minrisk": 0.0005}
        rows.append((v, run(data, v, a), run(data, v, b)))
    current = {"or": 15, "stop": "mid", "r": 2.0, "vol": 0.0, "vwap": False, "trend": False, "window": 69,
               "max": 3, "minrisk": 0.0005}
    print("AKTUELL", run(data, current, a), run(data, current, b), "gesamt", run(data, current, days))
    rows.sort(key=lambda x: -min(x[1]["avgR"], x[2]["avgR"]))
    good = [x for x in rows if x[1]["trades"] >= 25 and x[2]["trades"] >= 25]
    pos = sum(1 for x in good if x[1]["avgR"] > 0 and x[2]["avgR"] > 0)
    print(f"{len(good)} Varianten mit genug Trades, in beiden Haelften positiv: {pos}")
    for v, x, y in good[:12]:
        print({k: v[k] for k in ("or", "stop", "r", "vol", "vwap", "trend", "window")}, x, y)
    print("SCHLECHTESTE", good[-1][0], good[-1][1], good[-1][2])
    with open(os.path.join(CACHE, "_grid.json"), "w") as f:
        json.dump(rows, f)


if __name__ == "__main__":
    main()
