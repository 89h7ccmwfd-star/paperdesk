"""Zustand der Konten: laden, atomar speichern, pruefen, Entscheidungen, Fehler und Orders protokollieren."""
import json
import os

from . import clock, config, logs
from .types import Any, Bar, Bars, Config, Dict, List, Optional, Order, Plan, Position, Session, State, Tuple  # noqa: F401


STATE = os.path.join(config.HOME, "site", "state.json")


def record_order(state: State, **o: Any) -> Order:
    """Jede Order mit Zeitpunkten, Preisen, Kosten und Status; abgelehnte auch."""
    o.setdefault("id", f"{int(clock.now_ts())}-{o.get('symbol', '')}-{len(state.get('orders', []))}")
    o.setdefault("createdAt", clock.iso())
    state.setdefault("orders", []).append(o)
    del state["orders"][:-config.MAX_ORDERS]
    logs.log("order", **{k: o.get(k) for k in ("id", "side", "symbol", "status", "filledQty", "fillPrice", "reason")})
    return o


def validate_state(state: State) -> List[str]:
    """Zustand vor dem Handeln pruefen; jede Abweichung stoppt neue Kaeufe (Not-Aus)."""
    problems = []
    for name in ("day", "swing"):
        acc = state.get("accounts", {}).get(name)
        if not isinstance(acc, dict):
            problems.append(f"Konto {name} fehlt")
            continue
        for k in ("startingCash", "cash", "equity", "realizedPnl"):
            if not isinstance(acc.get(k), (int, float)):
                problems.append(f"{name}.{k} fehlt")
        if isinstance(acc.get("cash"), (int, float)) and acc["cash"] < 0:
            problems.append(f"{name}: Bargeld negativ")
        for p in acc.get("positions", []):
            if not (isinstance(p.get("qty"), int) and p["qty"] > 0 and p.get("entry", 0) > 0 and p.get("stop", 0) > 0):
                problems.append(f"{name}: Position {p.get('symbol')} ungueltig")
        if not isinstance(acc.get("journal"), list):
            problems.append(f"{name}.journal fehlt")
    return problems


def note_error(state: State, where: str, err: Any) -> None:
    state.setdefault("errors", []).append({"timestamp": clock.iso(), "where": where, "message": str(err)[:160]})
    del state["errors"][:-config.MAX_ERRORS]
    logs.log("error", where=where, message=str(err)[:160])


def load() -> State:
    with open(STATE, encoding="utf-8") as f:
        return json.load(f)


def save(state: State) -> None:
    state["updatedAt"] = clock.iso()
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def recalc(state: State) -> None:
    for acc in state["accounts"].values():
        acc["equity"] = round(acc["cash"] + sum(p["qty"] * p.get("last", p["entry"]) for p in acc["positions"]), 2)


def decide(state: State, symbol: str, outcome: str, detail: str) -> None:
    state.setdefault("decisions", []).append({"timestamp": clock.iso(), "symbol": symbol, "outcome": outcome,
                                              "detail": detail})
    del state["decisions"][:-config.MAX_DECISIONS]
    logs.log("decision", symbol=symbol, outcome=outcome, detail=detail)


def today_entries(acc: Dict[str, Any]) -> List[Dict[str, Any]]:
    day = clock.ny().date().isoformat()
    return [j for j in acc["journal"] if j["timestamp"][:10] == day]
