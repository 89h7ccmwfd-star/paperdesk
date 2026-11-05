#!/usr/bin/env python3
"""Wachhund: Ist die Boerse offen und der Stand aelter als 25 Minuten, steht der Bot. Ausgabe fuer GitHub Actions."""
import datetime as dt
import sys

import paper

MAX_AGE_MIN = 25


def stale_minutes(state, s, now):
    """Minuten seit dem letzten Stand, wenn die Boerse offen ist und der Stand zu alt ist, sonst None."""
    if not s["open"]:
        return None
    age = (now - dt.datetime.fromisoformat(state["updatedAt"]).timestamp()) / 60
    return round(age) if age > MAX_AGE_MIN else None


if __name__ == "__main__":
    age = stale_minutes(paper.load(), paper.session(), paper.now_ts())
    print(f"stale={age if age is not None else ''}")
    sys.exit(0)
