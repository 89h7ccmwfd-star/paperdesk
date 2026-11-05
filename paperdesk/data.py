"""Kursdaten von Yahoo: Abruf mit Protokoll, nur abgeschlossene und plausible Kerzen, Pruefung auf Luecken, Tagesarchiv."""
import json
import os
import subprocess
import time

from . import clock, config
from .types import Any, Bar, Bars, Config, Dict, List, Optional, Order, Plan, Position, Session, State, Tuple  # noqa: F401


FETCH_LOG = []


def curl(url: str) -> str:
    return subprocess.run(["/usr/bin/curl", "-sS", "-m", "20", "-A", "Mozilla/5.0", url],
                          capture_output=True, text=True, check=True).stdout


def fetch(symbol: str, interval: str, range_: str) -> Dict[str, Any]:
    entry = {"symbol": symbol, "interval": interval, "at": time.time(), "ok": False}
    FETCH_LOG.append(entry)
    chart = json.loads(curl(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                            f"?interval={interval}&range={range_}"))["chart"]
    if chart.get("error") or not chart.get("result"):
        raise RuntimeError(f"Keine Kursdaten fuer {symbol}")
    entry["ok"] = True
    return chart["result"][0]


def rows(result: Dict[str, Any], bar: int = config.BAR) -> Bars:
    """Nur abgeschlossene Kerzen: laufende und leere werden verworfen."""
    now = clock.now_ts()
    q = result["indicators"]["quote"][0]
    out, seen = [], set()
    for i, t in enumerate(result.get("timestamp") or []):
        vals = [q[k][i] for k in ("open", "high", "low", "close", "volume")]
        if None in vals or (bar == config.BAR and t % config.BAR) or t + bar > now or t in seen:
            continue
        o, h, l, c, v = vals
        # Unplausible Kerzen nicht verwenden: Tief ueber Eroeffnung/Schluss, Hoch darunter, Preis oder Volumen negativ.
        if not (0 < l <= min(o, c) and h >= max(o, c) and v >= 0):
            continue
        seen.add(t)
        out.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v})
    return out


def bar_index(b: Bar, start: float) -> int:
    """Nummer des 5-Minuten-Balkens seit Boersenstart, aus der Zeit statt aus der Listenposition."""
    return int((b["t"] - start) // config.BAR)


def first_bar(bars: Bars, start: float) -> Optional[Bar]:
    """Der Erstbalken gilt nur, wenn er wirklich um Boersenstart beginnt."""
    return bars[0] if bars and bars[0]["t"] == start else None


def check_bars(bars: Bars, start: float, now: float) -> Optional[str]:
    """Luecken und Verspaetung pruefen. Gibt den Grund zurueck oder None, wenn die Daten taugen.
    Eine Kerze Verspaetung ist erlaubt (Yahoo braucht nach Kerzenschluss manchmal etwas)."""
    if not bars:
        return "keine Kerzen"
    have = {bar_index(b, start) for b in bars}
    last = max(have)
    missing = [i for i in range(0, last + 1) if i not in have]
    if missing:
        return f"{len(missing)} fehlende Kerze(n), erste Nr. {missing[0]}"
    expected = min(int((now - start) // config.BAR) - 1, 77)
    if expected - last > 1:
        return f"Daten {expected - last} Kerzen alt"
    return None


def session_bars(result: Dict[str, Any]) -> Bars:
    out = []
    for b in rows(result):
        t = clock.ny(b["t"])
        if (t.hour, t.minute) >= (9, 30) and t.hour < 16:
            out.append(b)
    return out


def day_context() -> Dict[str, Dict[str, float]]:
    """Einmal am Tag: Erstbalken-Volumen und ATR der letzten Sitzungen je Aktie, ohne den heutigen Tag."""
    today = clock.ny().date().isoformat()
    path = os.path.join(config.HOME, "cache", f"ctx_{today}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    out = {}
    for symbol in config.UNIVERSE:
        try:
            days = {}
            for b in session_bars(fetch(symbol, "5m", "1mo")):
                days.setdefault(clock.ny(b["t"]).date().isoformat(), []).append(b)
        except config.DATA_ERRORS:
            continue
        hist = [days[d] for d in sorted(days) if d < today and len(days[d]) >= 70][-15:]
        if len(hist) < 15:
            continue
        ranges = []
        for a, b in zip(hist, hist[1:]):
            hi, lo, prev = max(x["h"] for x in b), min(x["l"] for x in b), a[-1]["c"]
            ranges.append(max(hi - lo, abs(hi - prev), abs(lo - prev)))
        out[symbol] = {"avgFirst": sum(b[0]["v"] for b in hist[-14:]) / 14, "atr": sum(ranges) / 14,
                       "prevClose": hist[-1][-1]["c"]}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return out


def archive(day: str, payload: Dict[str, Any]) -> None:
    """Eingangsdaten eines Tages im Repo ablegen, damit jede Entscheidung nachrechenbar bleibt."""
    path = os.path.join(config.HOME, "data", f"{day}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    old.update(payload)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def full_sessions(symbol: str) -> Dict[str, Bars]:
    days = {}
    for b in session_bars(fetch(symbol, "5m", "60d")):
        days.setdefault(clock.ny(b["t"]).date().isoformat(), []).append(b)
    today = clock.ny().date().isoformat()
    return {d: bars for d, bars in sorted(days.items()) if len(bars) == 78 and d != today}
