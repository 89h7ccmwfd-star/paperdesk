"""Kennzahlen des Papierhandels aus dem Journal. Reine Funktionen, ohne Netz.

Taegliche Renditen beziehen sich auf das Kapital zu Tagesbeginn; Sharpe und Sortino annualisiert mit 252 Handelstagen,
ohne risikofreien Zins. Unter 2 Handelstagen mit Ergebnis gibt es keine Sharpe- oder Sortino-Zahl.
"""
import datetime as dt
import math
import random

TRADING_DAYS = 252
MINUTES_PER_DAY = 390


def round_trips(journal):
    """Kauf und Verkauf je Aktie zu einem Trade zusammenfuehren (Reihenfolge des Journals)."""
    open_, out = {}, []
    for j in journal:
        if j["action"] == "BUY":
            open_[j["symbol"]] = j
        elif j["action"] == "SELL" and j["symbol"] in open_:
            b = open_.pop(j["symbol"])
            t0, t1 = dt.datetime.fromisoformat(b["timestamp"]), dt.datetime.fromisoformat(j["timestamp"])
            out.append({"symbol": j["symbol"], "strategy": b.get("strategy", "vor Versionierung"),
                        "buyAt": b["timestamp"], "sellAt": j["timestamp"], "qty": j["qty"], "entry": b["price"],
                        "exit": j["price"], "pnl": j["pnl"], "fees": b.get("fee", 0) + j.get("fee", 0),
                        "holdMin": (t1 - t0).total_seconds() / 60, "cost": b["price"] * j["qty"],
                        "plannedRisk": b.get("plannedRisk"), "note": b.get("note") or j.get("note")})
    return out


def mean_ci(values, n=5000, seed=19):
    if not values:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(n))
    return {"low": means[int(0.025 * n)], "high": means[int(0.975 * n) - 1]}


def drawdown(values):
    """Groesster Rueckgang einer Kapitalkurve in USD und Prozent vom Hoch."""
    peak, dd, ddp = values[0], 0.0, 0.0
    for v in values:
        peak = max(peak, v)
        dd = min(dd, v - peak)
        ddp = min(ddp, (v - peak) / peak if peak else 0)
    return dd, ddp


def metrics(journal, start_cash, orders=(), strategy=None, exclude_notes=True):
    """Kennzahlen fuer abgeschlossene Trades. exclude_notes laesst als Fehlbuchung markierte Trades weg."""
    trips = round_trips(journal)
    if strategy:
        trips = [t for t in trips if t["strategy"] == strategy]
    if exclude_notes:
        trips = [t for t in trips if not t["note"]]
    n = len(trips)
    out = {"trades": n, "strategy": strategy or "alle"}
    if not n:
        return out
    pnls = [t["pnl"] for t in trips]
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p <= 0]
    net = sum(pnls)
    fees = sum(t["fees"] for t in trips)
    gross = [p + t["fees"] for p, t in zip(pnls, trips)]
    by_day = {}
    for t in trips:
        by_day.setdefault(t["sellAt"][:10], 0.0)
        by_day[t["sellAt"][:10]] += t["pnl"]
    equity, curve, rets = start_cash, [start_cash], []
    for day in sorted(by_day):
        rets.append(by_day[day] / equity)
        equity += by_day[day]
        curve.append(equity)
    sharpe = sortino = None
    if len(rets) >= 2:
        mu, sd = sum(rets) / len(rets), _stdev(rets)
        if sd > 0:
            sharpe = mu / sd * math.sqrt(TRADING_DAYS)
        down = math.sqrt(sum(min(r, 0) ** 2 for r in rets) / len(rets))
        if down > 0:
            sortino = mu / down * math.sqrt(TRADING_DAYS)
    dd, ddp = drawdown(curve)
    traded = {t["symbol"] for t in trips}
    slip = sum(o.get("costPerShare", 0) * o.get("filledQty", 0) for o in orders
               if o.get("status") in ("filled", "partial") and o.get("symbol") in traded)
    turnover = sum(t["cost"] + t["exit"] * t["qty"] for t in trips)
    by_month = {}
    for t in trips:
        by_month[t["sellAt"][:7]] = round(by_month.get(t["sellAt"][:7], 0) + t["pnl"], 2)
    rs = [t["pnl"] / t["plannedRisk"] for t in trips if t.get("plannedRisk")]
    out.update({
        "netPnl": round(net, 2), "returnPct": round(net / start_cash * 100, 2),
        "winRate": round(len(wins) / n, 4), "avgWin": round(sum(wins) / len(wins), 2) if wins else None,
        "avgLoss": round(sum(losses) / len(losses), 2) if losses else None,
        "profitFactor": round(sum(wins) / -sum(losses), 3) if losses and sum(losses) < 0 else None,
        "expectancy": round(net / n, 2), "expectancyCI": mean_ci(pnls), "avgR": round(sum(rs) / len(rs), 3) if rs else None,
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "sortino": round(sortino, 2) if sortino is not None else None,
        "maxDrawdown": round(dd, 2), "maxDrawdownPct": round(ddp * 100, 2),
        "recoveryFactor": round(net / -dd, 2) if dd < 0 else None,
        "avgHoldMin": round(sum(t["holdMin"] for t in trips) / n, 1),
        "exposurePct": round(sum(min(t["holdMin"], MINUTES_PER_DAY) for t in trips) / (len(by_day) * MINUTES_PER_DAY) * 100, 1),
        "turnover": round(turnover / start_cash, 2), "fees": round(fees, 2),
        "feeSharePct": round(fees / sum(abs(g) for g in gross) * 100, 1) if any(gross) else None,
        "slippageCost": round(slip, 2), "days": len(by_day), "byMonth": by_month,
    })
    return out


def _stdev(xs):
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def report(state):
    """Kennzahlen je Konto und je Strategieversion fuer das Dashboard."""
    out = {}
    for name, acc in state["accounts"].items():
        trips = round_trips(acc["journal"])
        versions = sorted({t["strategy"] for t in trips})
        out[name] = {"all": metrics(acc["journal"], acc["startingCash"], state.get("orders", [])),
                     "byStrategy": {v: metrics(acc["journal"], acc["startingCash"], state.get("orders", []), v)
                                    for v in versions}}
    return out
