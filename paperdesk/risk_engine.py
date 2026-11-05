"""Risikopruefung direkt vor jeder Buchung, Tagesergebnis der Daytrades."""


from . import clock, config, ledger
from .types import Any, Bar, Bars, Config, Dict, List, Optional, Order, Plan, Position, Session, State, Tuple  # noqa: F401


# Risk Manager: harte Pruefung direkt vor jeder Buchung.
def risk_block(state: State, account: str, symbol: str, qty: int, price: float, stop: float, target: Optional[float], market: float, s: Session, c: Config) -> Optional[str]:
    acc = state["accounts"][account]
    entries = ledger.today_entries(acc)
    buys = sum(1 for j in entries if j["action"] == "BUY")
    if any(p["symbol"] == symbol for a in state["accounts"].values() for p in a["positions"]):
        return "Aktie schon offen"
    if any(j["symbol"] == symbol and j["action"] == "BUY" for j in entries):
        return "Aktie heute schon gehandelt"
    if account == "day":
        if buys >= c["max_day_trades"]:
            return "Tageslimit Trades erreicht"
        realized = sum(j.get("pnl", 0) for j in entries if j["action"] == "SELL")
        open_risk = sum(max(p["entry"] - p["stop"], 0) * p["qty"] for p in acc["positions"])
        if -realized + open_risk + max(price - stop, 0) * qty > c["max_day_loss"]:
            return "Tagesverlustgrenze: gebuchte Verluste plus offenes Risiko zu hoch"
        if not s["noEntryBefore"] <= clock.now_ts() < s["noEntryAfter"]:
            return "ausserhalb der Einstiegszeit"
    else:
        if buys >= c["max_swing_new"]:
            return "heute schon ein Swing-Kauf"
        if len(acc["positions"]) >= c["max_swing_open"]:
            return "schon zwei offene Swing-Positionen"
    if abs(price - market) / market > 0.005:
        return f"Kaufkurs {price} weicht vom Markt {market:.2f} ab"
    if not 0 < (price - stop) * qty <= c["max_risk"] or (target and target <= price) or qty < 1:
        return "Risiko oder Ziel ungueltig"
    if qty * price + config.fee(qty) > acc["cash"]:
        return "zu wenig virtuelles Geld"
    return None


def day_pnl(state: State) -> Tuple[float, float]:
    """Gebuchtes und offenes Ergebnis der heutigen Daytrades."""
    acc = state["accounts"]["day"]
    realized = sum(j.get("pnl", 0) for j in ledger.today_entries(acc) if j["action"] == "SELL")
    unrealized = sum(p["qty"] * (p.get("last", p["entry"]) - p["entry"]) for p in acc["positions"])
    return realized, unrealized
