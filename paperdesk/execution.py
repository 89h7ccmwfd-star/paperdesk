"""Simulierte Ausfuehrung: Kauf und Verkauf buchen, Kosten und Order-Protokoll."""


from . import clock, config, ledger
from .types import Any, Bar, Bars, Config, Dict, List, Optional, Order, Plan, Position, Session, State, Tuple  # noqa: F401


def buy(state: State, account: str, symbol: str, p: Plan, source: str, reason: str) -> None:
    acc = state["accounts"][account]
    f = config.fee(p["qty"])
    acc["cash"] = round(acc["cash"] - p["qty"] * p["entry"] - f, 2)
    acc["positions"].append({"symbol": symbol, "side": "Long", "qty": p["qty"], "entry": p["entry"],
                             "stop": p["stop"], "target": p["target"], "entryFee": f, "openedAt": clock.iso(),
                             "source": source, "last": p["entry"]})
    acc["journal"].append({"timestamp": clock.iso(), "action": "BUY", "symbol": symbol, "qty": p["qty"],
                           "price": p["entry"], "stop": p["stop"], "target": p["target"], "fee": f,
                           "plannedRisk": p["plannedRisk"], "source": source, "reason": reason})
    ledger.recalc(state)


def sell(state: State, account: str, pos: Position, price: float, reason: str, slip: float = 0.0) -> None:
    ref = price
    price = round(price * (1 - slip), 2)
    acc = state["accounts"][account]
    ledger.record_order(state, account=account, strategy=pos.get("strategy"), side="SELL", symbol=pos["symbol"],
                 type="stop" if reason == "Stop" else "market", executedAt=clock.iso(), requestedQty=pos["qty"],
                 filledQty=pos["qty"], refPrice=round(ref, 4), fillPrice=price, costPerShare=round(ref - price, 4),
                 fee=config.fee(pos["qty"]), status="filled", reason=reason)
    f = config.fee(pos["qty"])
    pnl = round((price - pos["entry"]) * pos["qty"] - pos["entryFee"] - f, 2)
    acc["cash"] = round(acc["cash"] + pos["qty"] * price - f, 2)
    acc["realizedPnl"] = round(acc["realizedPnl"] + pnl, 2)
    acc["positions"].remove(pos)
    acc["journal"].append({"timestamp": clock.iso(), "action": "SELL", "symbol": pos["symbol"], "qty": pos["qty"],
                           "price": price, "fee": f, "pnl": pnl, "source": "Yahoo 5m", "reason": reason})
    ledger.recalc(state)
