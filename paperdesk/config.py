"""Konfiguration, Konstanten, Kosten- und Groessenregeln. Einzige Quelle aller Limits."""
from .types import Any, Bar, Bars, Config, Dict, List, Optional, Order, Plan, Position, Session, State, Tuple  # noqa: F401
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo


HOME = os.environ.get("PAPER_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(HOME, "config.json")
NY = ZoneInfo("America/New_York")
BAR = 300
SEED = 19
REPLAYS = 10000
PUBLISH_EVERY = 3600
MAX_DECISIONS = 60

# Grenzen fuer die abendliche Analyse: sie darf nur innerhalb dieser Werte verstellen.
DEFAULTS = {"rv": 1.0, "gap": 0.005, "top": 5, "atr": 0.25, "window": 12, "max_risk": 50.0, "max_position": 3000.0,
            "max_day_loss": 100.0, "max_day_trades": 3, "max_swing_open": 2, "max_swing_new": 1, "slippage": 0.0004,
            "spread": 0.0004, "max_volume_share": 0.01}
# Erlaubte Bereiche je Schluessel; alles andere in config.json ist ein Fehler.
SCHEMA = {"rv": (0.5, 5), "gap": (0, 0.1), "top": (1, 20), "atr": (0.05, 2), "window": (1, 77), "max_risk": (1, 5000),
          "max_position": (100, 100000), "max_day_loss": (1, 10000), "max_day_trades": (1, 20), "max_swing_open": (0, 10),
          "max_swing_new": (0, 10), "slippage": (0, 0.01), "spread": (0, 0.02), "max_volume_share": (0.001, 0.5)}
DATA_ERRORS = (RuntimeError, ValueError, KeyError, IndexError, TypeError, subprocess.CalledProcessError, ET.ParseError)
MAX_ERRORS = 20
MAX_ORDERS = 300

# NYSE-Kalender laut nyse.com/markets/hours-calendars (gelesen 13.10.2026). Danach bricht der Bot bewusst ab.
HOLIDAYS = {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
            "2026-09-07", "2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
            "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"}
EARLY_CLOSE = {"2026-11-27", "2026-12-24", "2027-11-26"}
CALENDAR_UNTIL = "2027-12-31"
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


def cost(c: Config) -> float:
    """Kosten je Seite als Anteil am Kurs: halber Spread plus Slippage. Gilt live und im Rueckblick."""
    return c["spread"] / 2 + c["slippage"]


def fill_qty(qty: int, bar_volume: float, c: Config) -> int:
    """Hoechstens ein Anteil des Volumens der letzten Kerze wird ausgefuehrt; der Rest verfaellt."""
    return max(0, min(qty, int(bar_volume * c["max_volume_share"])))


def fee(qty: int) -> float:
    """Annahme: 0,005 USD je Aktie, mindestens 1 USD je Ausfuehrung."""
    return round(max(1.0, 0.005 * qty), 2)


def cfg() -> Config:
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
