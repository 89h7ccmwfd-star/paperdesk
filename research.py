#!/usr/bin/env python3
"""Statistische Pruefung der Daytrade-Regel, ohne Blick in die Zukunft.

- Jede gerechnete Variante landet in research/variants.jsonl (Mehrfachtests werden sichtbar).
- Walk-Forward: Parameter nur aus vergangenen Tagen waehlen, an den folgenden Tagen pruefen.
- Bootstrap-Konfidenzintervalle und Reality Check (White) gegen Datenschnueffelei ueber das ganze Raster.
- Vergleiche: zufaelliger Einstieg mit sonst gleichen Regeln, SPY von Eroeffnung bis Schluss.
- Regime: Tage mit steigendem und fallendem Gesamtmarkt getrennt.
- Die eingefrorene Regel (research/freeze.json) wird hier nicht veraendert; der unberuehrte Test ist der Papierhandel ab holdoutStart.

Aufruf: python3 research.py  (schreibt research/report.json)
"""
import datetime as dt
import hashlib
import itertools
import json
import os
import random
import statistics

import backtest as bt
import backtest2 as b2
import paper

DIR = os.path.join(paper.HOME, "research")
SEED = 19
BASE = {"rv": 1.0, "gap": 0.005, "top": 5, "atr": 0.25, "r": 0, "mkt": True, "window": 12, "max": 3, "next": True}
GRID = {"top": [3, 5, 8], "atr": [0.2, 0.25, 0.3], "rv": [1.0, 1.25], "gap": [0.003, 0.005], "r": [0, 1.0]}
TRAIN, TEST = 20, 6


def key(v):
    return json.dumps({k: v[k] for k in sorted(v)}, sort_keys=True)


def variants():
    names = sorted(GRID)
    return [dict(BASE, **dict(zip(names, vals))) for vals in itertools.product(*(GRID[n] for n in names))]


def day_results(data, spy, days, alldays, dailies, v, c):
    """Je Handelstag: Ergebnis in USD und die R-Werte der Trades. alldays enthaelt auch die 15 Vorlauftage."""
    out = {}
    for d in days:
        trades = b2.in_play(data, spy, v, d, alldays, dailies, c)
        out[d] = {"pnl": sum(t["pnl"] for t in trades), "r": [t["r"] for t in trades]}
    return out


def walk_forward(matrix, days, train=TRAIN, test=TEST):
    """Waehlt je Abschnitt die Variante mit dem hoechsten Schnitt der Trainingstage und rechnet sie an den Testtagen.
    matrix: {variante: {tag: pnl}}. Gibt Abschnitte und die Testtage-Ergebnisse zurueck."""
    folds, oos = [], []
    for s in range(0, len(days) - train - test + 1, test):
        tr, te = days[s:s + train], days[s + train:s + train + test]
        assert max(tr) < min(te), "Trainingstage muessen vor den Testtagen liegen"
        best = max(matrix, key=lambda k: (sum(matrix[k][d] for d in tr) / len(tr), k))
        res = [matrix[best][d] for d in te]
        folds.append({"train": [tr[0], tr[-1]], "test": [te[0], te[-1]], "chosen": best,
                      "trainMean": round(sum(matrix[best][d] for d in tr) / len(tr), 2), "testPnl": round(sum(res), 2)})
        oos += list(zip(te, res))
    return folds, oos


def bootstrap_ci(values, n=10000, seed=SEED, level=0.95):
    """Konfidenzintervall des Mittelwerts durch Ziehen mit Zuruecklegen."""
    if not values:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(n))
    lo, hi = means[int((1 - level) / 2 * n)], means[int((1 + level) / 2 * n) - 1]
    return {"mean": sum(values) / len(values), "low": lo, "high": hi, "n": len(values),
            "shareAtOrBelowZero": sum(m <= 0 for m in means) / n}


def reality_check(matrix, days, n=2000, block=5, seed=SEED):
    """White's Reality Check: Ist der beste Schnitt des ganzen Rasters besser als Zufall?
    Block-Bootstrap der Tage, Reihen um ihren Mittelwert zentriert. p-Wert = Anteil, in dem das Beste aus Rauschen
    mindestens so gut ist wie das tatsaechlich Beste."""
    keys = list(matrix)
    series = {k: [matrix[k][d] for d in days] for k in keys}
    means = {k: sum(v) / len(v) for k, v in series.items()}
    best = max(means.values())
    rng = random.Random(seed)
    T = len(days)
    hits = 0
    for _ in range(n):
        idx = []
        while len(idx) < T:
            s = rng.randrange(T)
            idx += [(s + j) % T for j in range(block)]
        idx = idx[:T]
        boot_best = max(sum(series[k][i] - means[k] for i in idx) / T for k in keys)
        hits += boot_best >= best
    return {"variants": len(keys), "bestMean": best, "p": hits / n}


def spy_benchmark(spy, days, notional, c):
    """SPY von der Eroeffnung bis Tagesschluss, gleicher Einsatz, gleiche Kosten."""
    out = {}
    for d in days:
        bars = spy.get(d) or []
        if len(bars) < 2:
            out[d] = 0.0
            continue
        buy, sell = bars[0]["o"] * (1 + c["slippage"]), bars[-1]["c"] * (1 - c["slippage"])
        qty = int(notional / buy)
        out[d] = (sell - buy) * qty - 2 * paper.fee(qty)
    return out


def log_variant(path, v, res, days, purpose):
    pnl = sum(x["pnl"] for x in res.values())
    rs = [r for x in res.values() for r in x["r"]]
    row = {"at": paper.iso(), "purpose": purpose, "id": hashlib.sha1(key(v).encode()).hexdigest()[:10], "params": v,
           "days": [days[0], days[-1], len(days)], "pnl": round(pnl, 2), "trades": len(rs)}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    os.makedirs(DIR, exist_ok=True)
    c = paper.cfg()
    data = bt.load_all(paper.UNIVERSE)
    spy = bt.load_all(["SPY"])["SPY"]
    alldays = sorted(x for x in {d for w in data.values() for d in w} if x < paper.ny().date().isoformat())
    dailies = {s: b2.daily(d, alldays) for s, d in data.items()}
    days = alldays[15:]
    log = os.path.join(DIR, "variants.jsonl")

    full = {}
    for v in variants():
        res = day_results(data, spy, days, alldays, dailies, v, c)
        full[key(v)] = res
        log_variant(log, v, res, days, "Raster fuer Walk-Forward und Reality Check")
    matrix = {k: {d: r["pnl"] for d, r in res.items()} for k, res in full.items()}
    frozen = full[key(BASE)]

    folds, oos = walk_forward(matrix, days)
    oos_days = [d for d, _ in oos]
    frozen_oos = [frozen[d]["pnl"] for d in oos_days]
    rnd = day_results(data, spy, days, alldays, dailies, dict(BASE, random=SEED), c)
    log_variant(log, dict(BASE, random=SEED), rnd, days, "Vergleich: zufaelliger Einstieg")
    spy_b = spy_benchmark(spy, days, c["max_position"], c)
    up = [d for d in days if spy.get(d) and spy[d][-1]["c"] > spy[d][0]["o"]]
    down = [d for d in days if d not in up]
    r_all = [r for d in days for r in frozen[d]["r"]]

    def part(ds):
        rs = [r for d in ds for r in frozen[d]["r"]]
        return {"days": len(ds), "pnl": round(sum(frozen[d]["pnl"] for d in ds), 2), "trades": len(rs),
                "avgR": round(sum(rs) / len(rs), 3) if rs else None}

    neighbours = []
    for name in GRID:
        for val in GRID[name]:
            if val == BASE[name]:
                continue
            k = key(dict(BASE, **{name: val}))
            neighbours.append({"change": f"{name}={val}", "pnl": round(sum(matrix[k].values()), 2)})

    report = {
        "at": paper.iso(), "days": [days[0], days[-1], len(days)], "gridSize": len(matrix),
        "note": "Aktienliste von heute (Survivorship Bias). Die eingefrorene Regel wurde vor dieser Studie an denselben "
                "Tagen ausgewaehlt; ihre Zahlen hier sind daher kein unabhaengiger Test. Unabhaengig ist nur Walk-Forward "
                "(Auswahl je Abschnitt nur aus der Vergangenheit) und der Papierhandel ab holdoutStart.",
        "frozen": {"params": BASE, "pnl": round(sum(frozen[d]["pnl"] for d in days), 2), "trades": len(r_all),
                   "dayCI": bootstrap_ci([frozen[d]["pnl"] for d in days]), "tradeRCI": bootstrap_ci(r_all)},
        "walkForward": {"train": TRAIN, "test": TEST, "folds": [dict(f, chosen=json.loads(f["chosen"])) for f in folds], "oosDays": len(oos),
                        "oosPnl": round(sum(p for _, p in oos), 2), "oosDayCI": bootstrap_ci([p for _, p in oos]),
                        "frozenSameDaysPnl": round(sum(frozen_oos), 2)},
        "realityCheck": reality_check(matrix, days),
        "benchmarks": {"randomEntryPnl": round(sum(x["pnl"] for x in rnd.values()), 2),
                       "randomEntryTrades": sum(len(x["r"]) for x in rnd.values()),
                       "spyOpenToClosePnl": round(sum(spy_b.values()), 2), "spyNotional": c["max_position"]},
        "regimes": {"spyUp": part(up), "spyDown": part(down)},
        "sensitivity": neighbours,
        "variantsLogged": sum(1 for _ in open(log, encoding="utf-8")),
        "variantsBeforeLog": "etwa 940 nicht einzeln protokolliert (480 + 288 + 144 + 32), siehe AUDIT.md Fund 11",
    }
    with open(os.path.join(DIR, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
