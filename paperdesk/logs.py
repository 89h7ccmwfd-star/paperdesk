"""Strukturierte Logs: eine JSON-Zeile je Ereignis auf stderr (stdout bleibt die Statuszeile fuer cloud-loop.sh)."""
import json
import sys

from . import clock


def log(event: str, **fields) -> None:
    print(json.dumps({"ts": clock.iso(), "event": event, **fields}, ensure_ascii=False, default=str), file=sys.stderr)
