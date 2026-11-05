"""Signale: In-Play-Liste, Ausloeser, Stop und Groesse, Swing-Setup, News-Sperre, Time Machine."""
import json
import math
import os
import random
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from . import clock, config, data
from .types import Any, Bar, Bars, Config, Dict, List, Optional, Order, Plan, Position, Session, State, Tuple  # noqa: F401


def find_trigger(bars: Bars, high: float, start: float, window: int) -> Optional[int]:
    """Position des ersten Balkens 1..window, der ueber dem Hoch des Erstbalkens schliesst. Gilt live und im Rueckblick."""
    for pos, b in enumerate(bars):
        i = data.bar_index(b, start)
        if i > window:
            break
        if i >= 1 and b["c"] > high:
            return pos
    return None


def strategy_version() -> str:
    """Version der eingefrorenen Regel (research/freeze.json), wird an jeden Kauf gehaengt."""
    try:
        with open(os.path.join(config.HOME, "research", "freeze.json"), encoding="utf-8") as f:
            return json.load(f)["version"]
    except (OSError, ValueError, KeyError):
        return "unbekannt"


def rank_in_play(state: State, c: Config, s: Session) -> Dict[str, Any]:
    """Nach dem ersten Balken: ungewoehnliches Volumen, gruener Balken, Gap nach oben. Die Top-Liste gilt den Tag."""
    today = clock.ny().date().isoformat()
    if state.get("inPlay", {}).get("date") == today:
        return state["inPlay"]
    ctx = data.day_context()
    ranked, first_bars = [], {}
    for symbol, x in ctx.items():
        try:
            bars = data.session_bars(data.fetch(symbol, "5m", "1d"))
        except config.DATA_ERRORS:
            continue
        first = data.first_bar(bars, s["start"])
        if not first:
            continue
        first_bars[symbol] = first
        rv = first["v"] / x["avgFirst"] if x["avgFirst"] else 0
        gap = first["o"] / x["prevClose"] - 1
        if rv >= c["rv"] and first["c"] > first["o"] and gap >= c["gap"]:
            ranked.append({"symbol": symbol, "rv": round(rv, 2), "gap": round(gap, 4), "atr": round(x["atr"], 4),
                           "high": first["h"], "done": False})
    ranked.sort(key=lambda r: -r["rv"])
    state["inPlay"] = {"date": today, "scanned": len(ctx), "matches": len(ranked), "symbols": ranked[:c["top"]]}
    data.archive(today, {"rankedAt": clock.iso(), "source": "Yahoo chart v8, 5m", "config": {k: c[k] for k in ("rv", "gap", "top")},
                    "context": ctx, "firstBars": first_bars, "inPlay": state["inPlay"]})
    return state["inPlay"]


def plan(entry: float, atr_value: float, c: Config) -> Tuple[Optional[Plan], Optional[str]]:
    """Stop in ATR-Bruchteilen unter dem Einstieg, kein festes Ziel: Gewinne laufen bis zum Tagesschluss."""
    entry = round(entry, 2)
    stop = math.floor((entry - c["atr"] * atr_value) * 100) / 100
    risk = entry - stop
    if risk <= 0:
        return None, "Stop liegt ueber dem Einstieg"
    if risk / entry < 0.0005:
        return None, "Stop zu eng fuer den Spread"
    qty = int(min(c["max_risk"] / risk, c["max_position"] / entry))
    if qty < 1:
        return None, "Risiko je Aktie groesser als das Limit"
    return {"entry": round(entry, 2), "stop": stop, "target": None, "qty": qty,
            "plannedRisk": round(qty * risk, 2)}, None


def time_machine(symbol: str, p: Plan, entry_index: int) -> Optional[Dict[str, Any]]:
    """Nur zur Information: 10.000 Wiederholungen aus den eigenen Balken der letzten 60 Tage. Sperrt keinen Kauf."""
    sessions = data.full_sessions(symbol)
    if len(sessions) < 20:
        return None
    pool = []
    for bars in sessions.values():
        ratios = [None]
        for i in range(1, 78):
            prev = bars[i - 1]["c"]
            ratios.append((bars[i]["l"] / prev, bars[i]["c"] / prev))
        pool.append(ratios)
    rng = random.Random(config.SEED)
    risk = p["entry"] - p["stop"]
    stopped = 0
    total_r = 0.0
    for _ in range(config.REPLAYS):
        price = p["entry"]
        hit = False
        for i in range(entry_index + 1, 78):
            low, close = rng.choice(pool)[min(77, max(1, i + rng.randint(-2, 2)))]
            if price * low <= p["stop"]:
                hit = True
                break
            price *= close
        stopped += hit
        total_r += -1.0 if hit else (price - p["entry"]) / risk
    return {"replays": config.REPLAYS, "seed": config.SEED, "stopFirst": round(stopped / config.REPLAYS, 3),
            "avgR": round(total_r / config.REPLAYS, 3)}


# News Monitor: nur Schlagzeilen, die das Unternehmen selbst nennen; schwere Meldungen der letzten 24 h sperren.
def news_check(symbol: str, name: str = "") -> Dict[str, Any]:
    xml = data.curl(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US")
    root = ET.fromstring(xml)
    flagged, seen = [], 0
    word = (re.findall(r"[A-Za-z]{4,}", name) or [symbol])[0]
    about = re.compile(rf"\b({re.escape(symbol)}|{re.escape(word)})\b", re.I)
    for item in root.iter("item"):
        when = item.findtext("pubDate")
        try:
            ts = parsedate_to_datetime(when).timestamp()
        except (TypeError, ValueError):
            continue
        if not 0 <= clock.now_ts() - ts <= 86400:
            continue
        seen += 1
        title = item.findtext("title") or ""
        if config.BAD_NEWS.search(title) and about.search(title):
            flagged.append(title[:120])
    return {"recent": seen, "flagged": flagged}


def daily_setup(symbol: str, price: float, c: Config) -> Optional[Plan]:
    """Einziges Tages-Setup, das im Rueckblick in beiden Haelften trug: Rueckeroberung des SMA20 im Aufwaertstrend."""
    bars = data.rows(data.fetch(symbol, "1d", "6mo"), bar=86400)
    today = clock.ny().date()
    bars = [b for b in bars if clock.ny(b["t"]).date() < today]
    if len(bars) < 50:
        return None
    closes = [b["c"] for b in bars]
    sma20 = sum(closes[-20:]) / 20
    sma20_before = sum(closes[-21:-1]) / 20
    sma50 = sum(closes[-50:]) / 50
    if not (closes[-2] < sma20_before and closes[-1] > sma20) or not price > sma20 > sma50:
        return None
    stop = math.floor(min(b["l"] for b in bars[-10:]) * 100) / 100
    risk = price - stop
    if risk <= 0 or risk / price > 0.08:
        return None
    qty = int(min(c["max_risk"] / risk, c["max_position"] / price))
    if qty < 1:
        return None
    return {"setup": "reclaim_ma20", "entry": round(price, 2), "stop": stop, "target": round(price + 2 * risk, 2),
            "qty": qty, "plannedRisk": round(qty * risk, 2)}
