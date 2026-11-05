#!/usr/bin/env python3
"""Paperdesk: nur Simulation. Keine Broker-Verbindung, keine echten Orders.

Einstieg fuer die Kommandozeile und Sammelstelle fuer aeltere Importe. Der Code liegt im Paket paperdesk:
config, clock, data, strategy, ledger, risk_engine, execution, engine, publishing.
"""
import fcntl
import json
import os
import sys

import analytics
from paperdesk import clock, config, data, engine, execution, ledger, publishing, risk_engine, strategy  # noqa: F401
from paperdesk.config import HOME, CONFIG, NY, BAR, SEED, REPLAYS, PUBLISH_EVERY, MAX_DECISIONS, DEFAULTS, SCHEMA, DATA_ERRORS, MAX_ERRORS, MAX_ORDERS, HOLIDAYS, EARLY_CLOSE, CALENDAR_UNTIL, BOUNDS, SWING_MAX_DAYS, UNIVERSE, BAD_NEWS, cost, fill_qty, fee, cfg  # noqa: F401,E501
from paperdesk.clock import now_ts, ny, iso, session  # noqa: F401,E501
from paperdesk.data import FETCH_LOG, curl, fetch, rows, bar_index, first_bar, check_bars, session_bars, day_context, archive, full_sessions  # noqa: F401,E501
from paperdesk.strategy import find_trigger, strategy_version, rank_in_play, plan, time_machine, news_check, daily_setup  # noqa: F401,E501
from paperdesk.ledger import STATE, validate_state, note_error, record_order, load, save, recalc, decide, today_entries  # noqa: F401,E501
from paperdesk.risk_engine import risk_block, day_pnl  # noqa: F401,E501
from paperdesk.execution import buy, sell  # noqa: F401,E501
from paperdesk.engine import manage, try_day, try_swing, remember_bars, describe, tick, stats  # noqa: F401,E501
from paperdesk.publishing import publish  # noqa: F401,E501


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    args = sys.argv[2:]
    with open(os.path.join(config.HOME, ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if cmd == "tick":
            engine.tick(do_publish="--no-publish" not in args)
        elif cmd == "stats":
            print(json.dumps({"stats": engine.stats(), "metrics": analytics.report(ledger.load()), "config": config.cfg(), "decisions": ledger.load().get("decisions", [])[-40:],
                              "bounds": config.BOUNDS}, ensure_ascii=False, indent=1))
        elif cmd == "review":
            state = ledger.load()
            state["review"] = {"at": clock.iso(), "text": args[0], "stats": engine.stats(), "config": config.cfg()}
            ledger.save(state)
            print(publishing.publish()[0])
        elif cmd == "set":
            key, value = args[0], float(args[1])
            if key not in config.BOUNDS or not config.BOUNDS[key][0] <= value <= config.BOUNDS[key][1]:
                raise SystemExit(f"Abgelehnt: {key} nur innerhalb von {BOUNDS.get(key)}.")
            c = config.cfg()
            c[key] = value
            with open(config.CONFIG, "w", encoding="utf-8") as f:
                json.dump(c, f, indent=1)
        elif cmd == "resume":
            state = ledger.load()
            problems = ledger.validate_state(state)
            if problems:
                raise SystemExit("Zustand weiter ungueltig: " + "; ".join(problems))
            state.pop("halt", None)
            ledger.save(state)
            print("Not-Aus aufgehoben")
        elif cmd == "publish":
            print(publishing.publish())
        else:
            raise SystemExit("Befehle: tick stats review set resume publish")


if __name__ == "__main__":
    main()
