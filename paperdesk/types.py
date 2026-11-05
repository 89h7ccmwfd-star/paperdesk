"""Gemeinsame Typen. Daten bleiben einfache dicts (JSON im Repo), die Typen benennen ihre Form."""
from typing import Any, Dict, List, Optional, Tuple

Bar = Dict[str, float]          # {"t": Sekunden, "o", "h", "l", "c", "v"}
Bars = List[Bar]
Config = Dict[str, float]       # validiert durch config.cfg()
State = Dict[str, Any]          # site/state.json
Session = Dict[str, Any]        # clock.session()
Plan = Dict[str, Any]           # strategy.plan(): entry, stop, target, qty, plannedRisk
Position = Dict[str, Any]
Order = Dict[str, Any]

__all__ = ["Any", "Bar", "Bars", "Config", "Dict", "List", "Optional", "Order", "Plan", "Position", "Session", "State",
           "Tuple"]
