#!/usr/bin/env python3
"""Paperdesk: nur Simulation. Keine Broker-Verbindung, keine echten Orders.

Daytrades: In-Play-Ausbruch nach dem ersten 5-Minuten-Balken (Regeln aus backtest2.py, dort gemessen).
Bausteine nach der Doku des Trader-Skills, eigener Code. Daten: Yahoo (kostenlos, inoffiziell, kann verzoegern).
"""
import datetime as dt
import fcntl
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

HOME = os.environ.get("PAPER_HOME") or os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HOME, "site", "state.json")
CONFIG = os.path.join(HOME, "config.json")
NY = ZoneInfo("America/New_York")
BAR = 300
SEED = 19
REPLAYS = 10000
PUBLISH_EVERY = 3600
MAX_DECISIONS = 60

# Grenzen fuer die abendliche Analyse: sie darf nur innerhalb dieser Werte verstellen.
DEFAULTS = {"rv": 1.0, "gap": 0.005, "top": 5, "atr": 0.25, "window": 12, "max_risk": 50.0, "max_position": 3000.0,
            "max_day_loss": 100.0, "max_day_trades": 3, "max_swing_open": 2, "max_swing_new": 1, "slippage": 0.0004}
# Erlaubte Bereiche je Schluessel; alles andere in config.json ist ein Fehler.
SCHEMA = {"rv": (0.5, 5), "gap": (0, 0.1), "top": (1, 20), "atr": (0.05, 2), "window": (1, 77), "max_risk": (1, 5000),
          "max_position": (100, 100000), "max_day_loss": (1, 10000), "max_day_trades": (1, 20), "max_swing_open": (0, 10),
          "max_swing_new": (0, 10), "slippage": (0, 0.01)}
DATA_ERRORS = (RuntimeError, ValueError, KeyError, IndexError, TypeError, subprocess.CalledProcessError, ET.ParseError)
MAX_ERRORS = 20

# NYSE-Kalender laut nyse.com/markets/hours-calendars (gelesen 13.10.2026). Danach bricht der Bot bewusst ab.
HOLIDAYS = {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
            "2026-09-07", "2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
            "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"}
EARLY_CLOSE = {"2026-11-27", "2026-12-24", "2027-11-26"}
CALENDAR_UNTIL = "2027-12-31"
FETCH_LOG = []
BOUNDS = {"rv": (1.0, 1.25), "gap": (0.003, 0.005), "atr": (0.2, 0.3)}
SWING_MAX_DAYS = 56

UNIVERSE = """AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO AMD NFLX COST LLY JPM V MA UNH XOM WMT ORCL CRM
BAC HD PG JNJ ABBV KO PEP MRK CVX ADBE CSCO ACN MCD TMO LIN ABT WFC DHR QCOM TXN INTU AMGN IBM GE
CAT NOW PM ISRG VZ GS MS AXP BKNG UBER T RTX SPGI BLK PFE LOW HON NEE UNP DE PLTR COIN SHOP MU
INTC LRCX KLAC AMAT PANW CRWD SNOW DDOG NET ABNB DIS SBUX NKE TGT BA F GM C SCHW PYPL SQ MRVL ARM
SMCI DELL HOOD RBLX CVS GILD VRTX REGN""".split()

# Quartalszahlen sperren nicht: Sie sind oft der Grund fuer den Ausbruch, und der Rueckblick misst mit ihnen.
BAD_NEWS = re.compile(r"\b(lawsuit|sued|probe|investigation|subpoena|fraud|restate|bankrupt|chapter 11|recall|"
                      r"ceo (?:steps?|resign|depart|out)|resigns|data breach|cyberattack|delist|share offering)\b", re.I)


def now_ts():
    pinned = os.environ.get("PAPER_NOW")
    if pinned:
        return dt.datetime.strptime(pinned, "%Y-%m-%d %H:%M").replace(tzinfo=NY).timestamp()
    return time.time()


def ny(ts=None):
    return dt.datetime.fromtimestamp(now_ts() if ts is None else ts, NY)


def iso(ts=None):
    return ny(ts).isoformat(timespec="seconds")


def fee(qty):
    """Annahme: 0,005 USD je Aktie, mindestens 1 USD je Ausfuehrung."""
    return round(max(1.0, 0.005 * qty), 2)


def cfg():
    c = dict(DEFAULTS)
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            c.update(json.load(f))
    bad = [k for k in c if k not in SCHEMA]
    bad += [k for k, (lo, hi) in SCHEMA.items()
            if isinstance(c.get(k), bool) or not isinstance(c.get(k), (int, float)) or not lo <= c[k] <= hi]
    if bad:
        raise SystemExit(f"Konfiguration ungueltig: {', '.join(sorted(set(bad)))}")
    return c


def curl(url):
    return subprocess.run(["/usr/bin/curl", "-sS", "-m", "20", "-A", "Mozilla/5.0", url],
                          capture_output=True, text=True, check=True).stdout


def fetch(symbol, interval, range_):
    entry = {"symbol": symbol, "interval": interval, "at": time.time(), "ok": False}
    FETCH_LOG.append(entry)
    chart = json.loads(curl(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                            f"?interval={interval}&range={range_}"))["chart"]
    if chart.get("error") or not chart.get("result"):
        raise RuntimeError(f"Keine Kursdaten fuer {symbol}")
    entry["ok"] = True
    return chart["result"][0]


def rows(result, bar=BAR):
    """Nur abgeschlossene Kerzen: laufende und leere werden verworfen."""
    now = now_ts()
    q = result["indicators"]["quote"][0]
    out, seen = [], set()
    for i, t in enumerate(result.get("timestamp") or []):
        vals = [q[k][i] for k in ("open", "high", "low", "close", "volume")]
        if None in vals or (bar == BAR and t % BAR) or t + bar > now or t in seen:
            continue
        o, h, l, c, v = vals
        # Unplausible Kerzen nicht verwenden: Tief ueber Eroeffnung/Schluss, Hoch darunter, Preis oder Volumen negativ.
        if not (0 < l <= min(o, c) and h >= max(o, c) and v >= 0):
            continue
        seen.add(t)
        out.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v})
    return out


def bar_index(b, start):
    """Nummer des 5-Minuten-Balkens seit Boersenstart, aus der Zeit statt aus der Listenposition."""
    return int((b["t"] - start) // BAR)


def first_bar(bars, start):
    """Der Erstbalken gilt nur, wenn er wirklich um Boersenstart beginnt."""
    return bars[0] if bars and bars[0]["t"] == start else None


def find_trigger(bars, high, start, window):
    """Position des ersten Balkens 1..window, der ueber dem Hoch des Erstbalkens schliesst. Gilt live und im Rueckblick."""
    for pos, b in enumerate(bars):
        i = bar_index(b, start)
        if i > window:
            break
        if i >= 1 and b["c"] > high:
            return pos
    return None


def strategy_version():
    """Version der eingefrorenen Regel (research/freeze.json), wird an jeden Kauf gehaengt."""
    try:
        with open(os.path.join(HOME, "research", "freeze.json"), encoding="utf-8") as f:
            return json.load(f)["version"]
    except (OSError, ValueError, KeyError):
        return "unbekannt"


def check_bars(bars, start, now):
    """Luecken und Verspaetung pruefen. Gibt den Grund zurueck oder None, wenn die Daten taugen.
    Eine Kerze Verspaetung ist erlaubt (Yahoo braucht nach Kerzenschluss manchmal etwas)."""
    if not bars:
        return "keine Kerzen"
    have = {bar_index(b, start) for b in bars}
    last = max(have)
    missing = [i for i in range(0, last + 1) if i not in have]
    if missing:
        return f"{len(missing)} fehlende Kerze(n), erste Nr. {missing[0]}"
    expected = min(int((now - start) // BAR) - 1, 77)
    if expected - last > 1:
        return f"Daten {expected - last} Kerzen alt"
    return None


def validate_state(state):
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


def note_error(state, where, err):
    state.setdefault("errors", []).append({"timestamp": iso(), "where": where, "message": str(err)[:160]})
    del state["errors"][:-MAX_ERRORS]


def session_bars(result):
    out = []
    for b in rows(result):
        t = ny(b["t"])
        if (t.hour, t.minute) >= (9, 30) and t.hour < 16:
            out.append(b)
    return out


def session():
    """Handelszeiten aus dem eigenen Boersenkalender: Wochenende, Feiertage, Halbtage bis 13:00 New York."""
    day = ny().date()
    key = day.isoformat()
    if key > CALENDAR_UNTIL:
        raise RuntimeError(f"Boersenkalender reicht nur bis {CALENDAR_UNTIL}, bitte ergaenzen")
    start = dt.datetime.combine(day, dt.time(9, 30), NY).timestamp()
    end = start + (12600 if key in EARLY_CLOSE else 23400)
    trading = day.weekday() < 5 and key not in HOLIDAYS
    now = now_ts()
    return {"date": key, "trading": trading, "start": start, "end": end, "open": trading and start <= now < end,
            "noEntryBefore": start + 300, "swingAfter": start + 900, "noEntryAfter": end - 1800, "flatBy": end - 300}


def day_context():
    """Einmal am Tag: Erstbalken-Volumen und ATR der letzten Sitzungen je Aktie, ohne den heutigen Tag."""
    today = ny().date().isoformat()
    path = os.path.join(HOME, "cache", f"ctx_{today}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    out = {}
    for symbol in UNIVERSE:
        try:
            days = {}
            for b in session_bars(fetch(symbol, "5m", "1mo")):
                days.setdefault(ny(b["t"]).date().isoformat(), []).append(b)
        except DATA_ERRORS:
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


def rank_in_play(state, c, s):
    """Nach dem ersten Balken: ungewoehnliches Volumen, gruener Balken, Gap nach oben. Die Top-Liste gilt den Tag."""
    today = ny().date().isoformat()
    if state.get("inPlay", {}).get("date") == today:
        return state["inPlay"]
    ctx = day_context()
    ranked, first_bars = [], {}
    for symbol, x in ctx.items():
        try:
            bars = session_bars(fetch(symbol, "5m", "1d"))
        except DATA_ERRORS:
            continue
        first = first_bar(bars, s["start"])
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
    archive(today, {"rankedAt": iso(), "source": "Yahoo chart v8, 5m", "config": {k: c[k] for k in ("rv", "gap", "top")},
                    "context": ctx, "firstBars": first_bars, "inPlay": state["inPlay"]})
    return state["inPlay"]


def archive(day, payload):
    """Eingangsdaten eines Tages im Repo ablegen, damit jede Entscheidung nachrechenbar bleibt."""
    path = os.path.join(HOME, "data", f"{day}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    old.update(payload)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def plan(entry, atr_value, c):
    """Stop in ATR-Bruchteilen unter dem Einstieg, kein festes Ziel: Gewinne laufen bis zum Tagesschluss."""
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


def full_sessions(symbol):
    days = {}
    for b in session_bars(fetch(symbol, "5m", "60d")):
        days.setdefault(ny(b["t"]).date().isoformat(), []).append(b)
    today = ny().date().isoformat()
    return {d: bars for d, bars in sorted(days.items()) if len(bars) == 78 and d != today}


def time_machine(symbol, p, entry_index):
    """Nur zur Information: 10.000 Wiederholungen aus den eigenen Balken der letzten 60 Tage. Sperrt keinen Kauf."""
    sessions = full_sessions(symbol)
    if len(sessions) < 20:
        return None
    pool = []
    for bars in sessions.values():
        ratios = [None]
        for i in range(1, 78):
            prev = bars[i - 1]["c"]
            ratios.append((bars[i]["l"] / prev, bars[i]["c"] / prev))
        pool.append(ratios)
    rng = random.Random(SEED)
    risk = p["entry"] - p["stop"]
    stopped = 0
    total_r = 0.0
    for _ in range(REPLAYS):
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
    return {"replays": REPLAYS, "seed": SEED, "stopFirst": round(stopped / REPLAYS, 3),
            "avgR": round(total_r / REPLAYS, 3)}


# News Monitor: nur Schlagzeilen, die das Unternehmen selbst nennen; schwere Meldungen der letzten 24 h sperren.
def news_check(symbol, name=""):
    xml = curl(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US")
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
        if not 0 <= now_ts() - ts <= 86400:
            continue
        seen += 1
        title = item.findtext("title") or ""
        if BAD_NEWS.search(title) and about.search(title):
            flagged.append(title[:120])
    return {"recent": seen, "flagged": flagged}


def daily_setup(symbol, price, c):
    """Einziges Tages-Setup, das im Rueckblick in beiden Haelften trug: Rueckeroberung des SMA20 im Aufwaertstrend."""
    bars = rows(fetch(symbol, "1d", "6mo"), bar=86400)
    today = ny().date()
    bars = [b for b in bars if ny(b["t"]).date() < today]
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


def load():
    with open(STATE, encoding="utf-8") as f:
        return json.load(f)


def save(state):
    state["updatedAt"] = iso()
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def recalc(state):
    for acc in state["accounts"].values():
        acc["equity"] = round(acc["cash"] + sum(p["qty"] * p.get("last", p["entry"]) for p in acc["positions"]), 2)


def decide(state, symbol, outcome, detail):
    state.setdefault("decisions", []).append({"timestamp": iso(), "symbol": symbol, "outcome": outcome,
                                              "detail": detail})
    del state["decisions"][:-MAX_DECISIONS]


def today_entries(acc):
    day = ny().date().isoformat()
    return [j for j in acc["journal"] if j["timestamp"][:10] == day]


# Risk Manager: harte Pruefung direkt vor jeder Buchung.
def risk_block(state, account, symbol, qty, price, stop, target, market, s, c):
    acc = state["accounts"][account]
    entries = today_entries(acc)
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
        if not s["noEntryBefore"] <= now_ts() < s["noEntryAfter"]:
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
    if qty * price + fee(qty) > acc["cash"]:
        return "zu wenig virtuelles Geld"
    return None


def buy(state, account, symbol, p, source, reason):
    acc = state["accounts"][account]
    f = fee(p["qty"])
    acc["cash"] = round(acc["cash"] - p["qty"] * p["entry"] - f, 2)
    acc["positions"].append({"symbol": symbol, "side": "Long", "qty": p["qty"], "entry": p["entry"],
                             "stop": p["stop"], "target": p["target"], "entryFee": f, "openedAt": iso(),
                             "source": source, "last": p["entry"]})
    acc["journal"].append({"timestamp": iso(), "action": "BUY", "symbol": symbol, "qty": p["qty"],
                           "price": p["entry"], "stop": p["stop"], "target": p["target"], "fee": f,
                           "plannedRisk": p["plannedRisk"], "source": source, "reason": reason})
    recalc(state)


def sell(state, account, pos, price, reason, slip=0.0):
    price = round(price * (1 - slip), 2)
    acc = state["accounts"][account]
    f = fee(pos["qty"])
    pnl = round((price - pos["entry"]) * pos["qty"] - pos["entryFee"] - f, 2)
    acc["cash"] = round(acc["cash"] + pos["qty"] * price - f, 2)
    acc["realizedPnl"] = round(acc["realizedPnl"] + pnl, 2)
    acc["positions"].remove(pos)
    acc["journal"].append({"timestamp": iso(), "action": "SELL", "symbol": pos["symbol"], "qty": pos["qty"],
                           "price": price, "fee": f, "pnl": pnl, "source": "Yahoo 5m", "reason": reason})
    recalc(state)


def day_pnl(state):
    """Gebuchtes und offenes Ergebnis der heutigen Daytrades."""
    acc = state["accounts"]["day"]
    realized = sum(j.get("pnl", 0) for j in today_entries(acc) if j["action"] == "SELL")
    unrealized = sum(p["qty"] * (p.get("last", p["entry"]) - p["entry"]) for p in acc["positions"])
    return realized, unrealized


def manage(state, s, c):
    """Stop vor Ziel; oeffnet eine Kerze unter dem Stop, wird zum Eroeffnungskurs verkauft. Daytrades flat by.
    Jeder Balken, der nach dem Kauf endet, zaehlt, auch der, in dem gekauft wurde (vorsichtig)."""
    changed = False
    for name, acc in state["accounts"].items():
        for p in list(acc["positions"]):
            since = dt.datetime.fromisoformat(p["openedAt"]).timestamp()
            try:
                bars = [b for b in session_bars(fetch(p["symbol"], "5m", "5d")) if b["t"] + BAR > since]
            except DATA_ERRORS as e:
                note_error(state, f"Position {p['symbol']}", e)
                continue
            if bars:
                p["last"] = round(bars[-1]["c"], 2)
            hit = None
            for b in bars:
                if b["l"] <= p["stop"]:
                    hit = (min(b["o"], p["stop"]), "Stop")
                    break
                if p["target"] and b["h"] >= p["target"]:
                    hit = (p["target"], "Ziel")
                    break
            if not hit and name == "swing" and now_ts() - since > SWING_MAX_DAYS * 86400:
                hit = (p["last"], "Zeitstopp nach 8 Wochen")
            if not hit and name == "day" and (now_ts() >= s["flatBy"] or not s["open"]):
                hit = (p["last"], "Flat by, Tagesschluss")
            if hit:
                sell(state, name, p, hit[0], hit[1], c["slippage"])
                changed = True
    realized, unrealized = day_pnl(state)
    if state["accounts"]["day"]["positions"] and realized + unrealized <= -c["max_day_loss"]:
        for p in list(state["accounts"]["day"]["positions"]):
            sell(state, "day", p, p.get("last", p["entry"]), "Tagesverlustgrenze erreicht", c["slippage"])
        changed = True
    recalc(state)
    return changed


def try_day(state, s, c):
    """Erster abgeschlossener Balken ueber dem Hoch des ersten Balkens, innerhalb der ersten Stunde, Markt im Plus."""
    changed = False
    inplay = rank_in_play(state, c, s)
    try:
        spy = session_bars(fetch("SPY", "5m", "1d"))
    except DATA_ERRORS as e:
        note_error(state, "SPY", e)
        return changed
    bad = check_bars(spy, s["start"], now_ts())
    if bad:
        note_error(state, "SPY", f"Daten: {bad}")
        return changed
    spy_open = first_bar(spy, s["start"])
    spy_at = {b["t"]: b for b in spy}
    if spy and spy_open:
        inplay["spyChangePct"] = round((spy[-1]["c"] / spy_open["o"] - 1) * 100, 2)
    window_end = s["start"] + (1 + c["window"]) * BAR
    inplay["windowEnd"] = iso(window_end)

    def skip(x, why):
        x["status"], x["why"] = "aussortiert", why
        decide(state, x["symbol"], "aussortiert", why)

    for x in inplay["symbols"]:
        if x["done"]:
            continue
        symbol = x["symbol"]
        try:
            result = fetch(symbol, "5m", "1d")
            bars = session_bars(result)
        except DATA_ERRORS as e:
            note_error(state, symbol, e)
            continue
        if bars:
            x["last"] = round(bars[-1]["c"], 2)
            x["distPct"] = round((bars[-1]["c"] / x["high"] - 1) * 100, 2)
        bad = check_bars(bars, s["start"], now_ts())
        if bad:
            # Keine Entscheidung auf unvollstaendigen Daten; naechster Lauf versucht es wieder.
            x["status"], x["why"] = "wartet", f"Daten unvollständig: {bad}"
            note_error(state, symbol, f"Daten: {bad}")
            changed = True
            if now_ts() >= window_end + 2 * BAR:
                x["done"] = True
                skip(x, f"Daten unvollständig: {bad}")
            continue
        pos = find_trigger(bars, x["high"], s["start"], c["window"])
        if pos is None:
            x["status"], x["why"] = "wartet", "Noch kein 5-Minuten-Schluss über dem Auslöser"
            changed = True
            if now_ts() >= window_end:
                x["done"] = True
                skip(x, "Kein Ausbruch in der ersten Stunde")
            continue
        x["done"] = True
        changed = True
        trig = bars[pos]
        spy_bar = spy_at.get(trig["t"])
        if not spy_open or not spy_bar:
            skip(x, "SPY-Daten fuer den Ausbruchsbalken fehlen")
            continue
        if spy_bar["c"] <= spy_open["o"]:
            skip(x, "Ausbruch, aber Gesamtmarkt (SPY) unter Eroeffnung")
            continue
        if bar_index(bars[-1], s["start"]) - bar_index(trig, s["start"]) > 1:
            skip(x, "Ausbruch verpasst, Bot lief zu spaet")
            continue
        last = bars[-1]["c"]
        p, why = plan(last * (1 + c["slippage"]), x["atr"], c)
        if not p:
            skip(x, why)
            continue
        block = risk_block(state, "day", symbol, p["qty"], p["entry"], p["stop"], p["target"], last, s, c)
        if block:
            skip(x, block)
            continue
        meta = result.get("meta", {})
        try:
            news = news_check(symbol, meta.get("longName") or meta.get("shortName") or "")
        except DATA_ERRORS as e:
            note_error(state, f"News {symbol}", e)
            skip(x, "News nicht abrufbar, Kauf ausgelassen")
            continue
        if news["flagged"]:
            skip(x, "News: " + news["flagged"][0])
            continue
        try:
            tm = time_machine(symbol, p, len(bars) - 1)
        except DATA_ERRORS:
            tm = None
        info = f"Time Machine: Stop zuerst {tm['stopFirst']:.0%}, Schnitt {tm['avgR']}R, Seed {tm['seed']}. " if tm else ""
        reason = (f"In Play: Volumen {x['rv']}x, Gap {x['gap']:.1%}, Ausbruch ueber {round(x['high'], 2)}, SPY im Plus. "
                  f"Stop {c['atr']} ATR, kein festes Ziel. {info}News: {news['recent']} Meldungen, keine schwere.")
        buy(state, "day", symbol, p, "Yahoo 5m", reason)
        state["accounts"]["day"]["journal"][-1]["trigger"] = round(x["high"], 2)
        state["accounts"]["day"]["journal"][-1]["strategy"] = strategy_version()
        x["status"], x["why"] = "gekauft", f"Gekauft zu {p['entry']}"
        decide(state, symbol, "gekauft", reason)
    return changed


def try_swing(state, s, c):
    acc = state["accounts"]["swing"]
    if any(j["action"] == "BUY" for j in today_entries(acc)) or len(acc["positions"]) >= c["max_swing_open"]:
        return False
    changed = False
    for symbol in UNIVERSE:
        try:
            bars = session_bars(fetch(symbol, "5m", "1d"))
            if not bars or now_ts() - bars[-1]["t"] > 900:
                continue
            last = bars[-1]["c"]
            p = daily_setup(symbol, last * (1 + c["slippage"]), c)
        except DATA_ERRORS:
            continue
        if not p or risk_block(state, "swing", symbol, p["qty"], p["entry"], p["stop"], p["target"], last, s, c):
            continue
        try:
            news = news_check(symbol, "")
        except DATA_ERRORS as e:
            note_error(state, f"News {symbol}", e)
            continue
        if news["flagged"]:
            decide(state, symbol, "aussortiert", "Swing, News: " + news["flagged"][0])
            changed = True
            continue
        reason = f"Tages-Setup {p['setup']}, Stop am 10-Tage-Tief, Ziel 2R. News: {news['recent']} Meldungen, keine schwere."
        buy(state, "swing", symbol, p, "Yahoo 5m", reason)
        state["accounts"]["swing"]["journal"][-1]["strategy"] = "swing-reclaim-1"
        decide(state, symbol, "gekauft", reason)
        return True
    return changed


def publish():
    """Laeuft nur mit Cloudflare-Token (GitHub-Secret) oder lokaler Freigabe (Datei .publish-enabled)."""
    if not (os.environ.get("CLOUDFLARE_API_TOKEN") or os.path.exists(os.path.join(HOME, ".publish-enabled"))):
        return False, "Hochladen nicht freigegeben"
    npx = shutil.which("npx") or "/usr/local/bin/npx"
    res = subprocess.run([npx, "--yes", "wrangler@3", "pages", "deploy", os.path.join(HOME, "site"),
                          "--project-name", "paperdesk-sim", "--branch", "main", "--commit-dirty=true"],
                         cwd=HOME, capture_output=True, text=True, timeout=240)
    return res.returncode == 0, (res.stdout + res.stderr)[-400:]


def tick(do_publish=True):
    state = load()
    c = cfg()
    s = session()
    changed = False
    del FETCH_LOG[:]
    problems = validate_state(state)
    if problems and not state.get("halt"):
        state["halt"] = {"at": iso(), "reasons": problems}
    if state.get("halt"):
        state["status"] = "Not-Aus: " + "; ".join(state["halt"]["reasons"]) + ". Weiter erst nach Pruefung (paper.py resume)."
        save(state)
        print(iso(), state["status"])
        return
    if s["open"]:
        changed |= manage(state, s, c)
        if s["noEntryBefore"] <= now_ts() < s["noEntryAfter"]:
            if now_ts() >= s["swingAfter"]:
                changed |= try_swing(state, s, c)
            changed |= try_day(state, s, c)
            ip = state.get("inPlay", {})
            state["status"] = (f"Markt offen. In Play heute: "
                               f"{', '.join(x['symbol'] for x in ip.get('symbols', [])) or 'keine'}.")
        else:
            state["status"] = "Markt offen, gerade keine neuen Einstiege erlaubt."
    else:
        # Verpasster Tagesschluss, etwa nach Ruhezustand: Daytrades nie ueber Nacht halten.
        if state["accounts"]["day"]["positions"]:
            changed |= manage(state, s, c)
        state["status"] = "Markt geschlossen."
    if s["open"]:
        remember_bars(state, s)
    describe(state, s, c)
    failed = [f["symbol"] for f in FETCH_LOG if not f["ok"]]
    state["dataQuality"] = {"at": iso(), "source": "Yahoo chart v8", "requests": len(FETCH_LOG), "failed": len(failed),
                            "failedSymbols": sorted(set(failed))[:10],
                            "issues": [e for e in state.get("errors", []) if e["timestamp"][:10] == s["date"]][-5:]}
    recalc(state)
    last = state.get("publishedAt", 0)
    due = do_publish and (changed or (s["open"] and now_ts() - last >= PUBLISH_EVERY))
    if due:
        state["publishedAt"] = now_ts()
    save(state)
    if due:
        ok, out = publish()
        print("publish", ok, "" if ok else out)
    print(iso(), state["status"], "changed" if changed else "")


def remember_bars(state, s):
    """Kurse der Aktien mit Trades fuer die Ansicht im Dashboard: Tag in 5 Minuten, Swing in Tagen."""
    store = state.setdefault("bars", {})
    today = ny().date().isoformat()
    day_syms = {p["symbol"] for p in state["accounts"]["day"]["positions"]}
    day_syms |= {j["symbol"] for j in state["accounts"]["day"]["journal"] if j["timestamp"][:10] == today}
    for symbol in day_syms:
        try:
            bars = session_bars(fetch(symbol, "5m", "1d"))
        except DATA_ERRORS:
            continue
        if bars:
            store[f"{ny(bars[-1]['t']).date().isoformat()}:{symbol}"] = [[b["t"], round(b["c"], 2)] for b in bars]
    swing_syms = {p["symbol"] for p in state["accounts"]["swing"]["positions"]}
    swing_syms |= {j["symbol"] for j in state["accounts"]["swing"]["journal"][-6:]}
    for symbol in swing_syms:
        try:
            bars = rows(fetch(symbol, "1d", "6mo"), bar=86400)
        except DATA_ERRORS:
            continue
        store[f"D:{symbol}"] = [[b["t"], round(b["c"], 2)] for b in bars]
    for key in sorted(k for k in store if not k.startswith("D:"))[:-30]:
        del store[key]


def describe(state, s, c):
    """Was der Bot gerade tut und wann er das naechste Mal kaufen kann, fuer das Dashboard."""
    now = now_ts()
    window_end = s["start"] + (1 + c["window"]) * BAR
    ip = state.get("inPlay", {})
    today = ny().date().isoformat()
    waiting = [x["symbol"] for x in ip.get("symbols", []) if ip.get("date") == today and not x["done"]]
    buys = sum(1 for j in today_entries(state["accounts"]["day"]) if j["action"] == "BUY")
    if not s["open"] and now < s["start"]:
        phase, text, nxt = "vorher", "Börse noch zu. Nach dem ersten 5-Minuten-Balken wählt der Bot die Tagesliste.", s["noEntryBefore"]
    elif not s["open"]:
        phase, text, nxt = "zu", "Börse zu. Morgen wählt der Bot nach dem ersten 5-Minuten-Balken die neue Tagesliste.", None
    elif now < s["noEntryBefore"]:
        phase, text, nxt = "start", "Der erste 5-Minuten-Balken läuft. Danach steht die Tagesliste fest.", s["noEntryBefore"]
    elif now < window_end and buys < c["max_day_trades"] and waiting:
        phase, nxt = "fenster", window_end
        text = (f"Beobachtet {', '.join(waiting)}. Gekauft wird beim ersten 5-Minuten-Schluss über dem Auslöser, "
                f"wenn der Gesamtmarkt (SPY) im Plus ist.")
    else:
        open_day = state["accounts"]["day"]["positions"]
        phase, nxt = "verwalten", s["flatBy"] if open_day else None
        text = ("Keine neuen Daytrades mehr heute. " +
                (f"Offene Daytrades werden am Stop oder spätestens {ny(s['flatBy']).strftime('%H:%M')} Uhr New York verkauft." if open_day
                 else "Der Bot wartet auf den nächsten Handelstag."))
    state["plan"] = {"phase": phase, "text": text, "next": iso(nxt) if nxt else None,
                     "windowEnd": iso(window_end), "dayBuys": buys, "maxDayTrades": c["max_day_trades"]}


def stats():
    state = load()
    out = {}
    for name, acc in state["accounts"].items():
        sells = [j for j in acc["journal"] if j["action"] == "SELL"]
        wins = [j["pnl"] for j in sells if j["pnl"] > 0]
        losses = [j["pnl"] for j in sells if j["pnl"] <= 0]
        out[name] = {"closed": len(sells), "wins": len(wins), "losses": len(losses),
                     "winRate": round(len(wins) / len(sells), 3) if sells else None,
                     "avgWin": round(sum(wins) / len(wins), 2) if wins else None,
                     "avgLoss": round(sum(losses) / len(losses), 2) if losses else None,
                     "pnl": acc["realizedPnl"], "equity": acc["equity"]}
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    args = sys.argv[2:]
    with open(os.path.join(HOME, ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if cmd == "tick":
            tick(do_publish="--no-publish" not in args)
        elif cmd == "stats":
            print(json.dumps({"stats": stats(), "config": cfg(), "decisions": load().get("decisions", [])[-40:],
                              "bounds": BOUNDS}, ensure_ascii=False, indent=1))
        elif cmd == "review":
            state = load()
            state["review"] = {"at": iso(), "text": args[0], "stats": stats(), "config": cfg()}
            save(state)
            print(publish()[0])
        elif cmd == "set":
            key, value = args[0], float(args[1])
            if key not in BOUNDS or not BOUNDS[key][0] <= value <= BOUNDS[key][1]:
                raise SystemExit(f"Abgelehnt: {key} nur innerhalb von {BOUNDS.get(key)}.")
            c = cfg()
            c[key] = value
            with open(CONFIG, "w", encoding="utf-8") as f:
                json.dump(c, f, indent=1)
        elif cmd == "resume":
            state = load()
            problems = validate_state(state)
            if problems:
                raise SystemExit("Zustand weiter ungueltig: " + "; ".join(problems))
            state.pop("halt", None)
            save(state)
            print("Not-Aus aufgehoben")
        elif cmd == "publish":
            print(publish())
        else:
            raise SystemExit("Befehle: tick stats review set resume publish")


if __name__ == "__main__":
    main()
