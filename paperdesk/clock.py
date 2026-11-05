"""Zeit (auch fest einstellbar ueber PAPER_NOW) und Boersenkalender."""
import datetime as dt
import os
import time

from . import config
from .types import Any, Bar, Bars, Config, Dict, List, Optional, Order, Plan, Position, Session, State, Tuple  # noqa: F401


def now_ts() -> float:
    pinned = os.environ.get("PAPER_NOW")
    if pinned:
        return dt.datetime.strptime(pinned, "%Y-%m-%d %H:%M").replace(tzinfo=config.NY).timestamp()
    return time.time()


def ny(ts: Optional[float] = None):
    return dt.datetime.fromtimestamp(now_ts() if ts is None else ts, config.NY)


def iso(ts: Optional[float] = None) -> str:
    return ny(ts).isoformat(timespec="seconds")


def session() -> Session:
    """Handelszeiten aus dem eigenen Boersenkalender: Wochenende, Feiertage, Halbtage bis 13:00 New York."""
    day = ny().date()
    key = day.isoformat()
    if key > config.CALENDAR_UNTIL:
        raise RuntimeError(f"Boersenkalender reicht nur bis {config.CALENDAR_UNTIL}, bitte ergaenzen")
    start = dt.datetime.combine(day, dt.time(9, 30), config.NY).timestamp()
    end = start + (12600 if key in config.EARLY_CLOSE else 23400)
    trading = day.weekday() < 5 and key not in config.HOLIDAYS
    now = now_ts()
    return {"date": key, "trading": trading, "start": start, "end": end, "open": trading and start <= now < end,
            "noEntryBefore": start + 300, "swingAfter": start + 900, "noEntryAfter": end - 1800, "flatBy": end - 300}
