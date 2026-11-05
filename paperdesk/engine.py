"""Ablauf eines Laufs: Positionen verwalten, Einstiege pruefen, Anzeige-Daten schreiben."""
import datetime as dt

import analytics

from . import clock, config, data, execution, ledger, publishing, risk_engine, strategy
from .types import Any, Bar, Bars, Config, Dict, List, Optional, Order, Plan, Position, Session, State, Tuple  # noqa: F401


def manage(state: State, s: Session, c: Config) -> bool:
    """Stop vor Ziel; oeffnet eine Kerze unter dem Stop, wird zum Eroeffnungskurs verkauft. Daytrades flat by.
    Jeder Balken, der nach dem Kauf endet, zaehlt, auch der, in dem gekauft wurde (vorsichtig)."""
    changed = False
    for name, acc in state["accounts"].items():
        for p in list(acc["positions"]):
            since = dt.datetime.fromisoformat(p["openedAt"]).timestamp()
            try:
                bars = [b for b in data.session_bars(data.fetch(p["symbol"], "5m", "5d")) if b["t"] + config.BAR > since]
            except config.DATA_ERRORS as e:
                ledger.note_error(state, f"Position {p['symbol']}", e)
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
            if not hit and name == "swing" and clock.now_ts() - since > config.SWING_MAX_DAYS * 86400:
                hit = (p["last"], "Zeitstopp nach 8 Wochen")
            if not hit and name == "day" and (clock.now_ts() >= s["flatBy"] or not s["open"]):
                hit = (p["last"], "Flat by, Tagesschluss")
            if hit:
                execution.sell(state, name, p, hit[0], hit[1], config.cost(c))
                changed = True
    realized, unrealized = risk_engine.day_pnl(state)
    if state["accounts"]["day"]["positions"] and realized + unrealized <= -c["max_day_loss"]:
        for p in list(state["accounts"]["day"]["positions"]):
            execution.sell(state, "day", p, p.get("last", p["entry"]), "Tagesverlustgrenze erreicht", config.cost(c))
        changed = True
    ledger.recalc(state)
    return changed


def try_day(state: State, s: Session, c: Config) -> bool:
    """Erster abgeschlossener Balken ueber dem Hoch des ersten Balkens, innerhalb der ersten Stunde, Markt im Plus."""
    changed = False
    inplay = strategy.rank_in_play(state, c, s)
    try:
        spy = data.session_bars(data.fetch("SPY", "5m", "1d"))
    except config.DATA_ERRORS as e:
        ledger.note_error(state, "SPY", e)
        return changed
    bad = data.check_bars(spy, s["start"], clock.now_ts())
    if bad:
        ledger.note_error(state, "SPY", f"Daten: {bad}")
        return changed
    spy_open = data.first_bar(spy, s["start"])
    spy_at = {b["t"]: b for b in spy}
    if spy and spy_open:
        inplay["spyChangePct"] = round((spy[-1]["c"] / spy_open["o"] - 1) * 100, 2)
    window_end = s["start"] + (1 + c["window"]) * config.BAR
    inplay["windowEnd"] = clock.iso(window_end)

    def skip(x, why):
        x["status"], x["why"] = "aussortiert", why
        ledger.decide(state, x["symbol"], "aussortiert", why)

    for x in inplay["symbols"]:
        if x["done"]:
            continue
        symbol = x["symbol"]
        try:
            result = data.fetch(symbol, "5m", "1d")
            bars = data.session_bars(result)
        except config.DATA_ERRORS as e:
            ledger.note_error(state, symbol, e)
            continue
        if bars:
            x["last"] = round(bars[-1]["c"], 2)
            x["distPct"] = round((bars[-1]["c"] / x["high"] - 1) * 100, 2)
        bad = data.check_bars(bars, s["start"], clock.now_ts())
        if bad:
            # Keine Entscheidung auf unvollstaendigen Daten; naechster Lauf versucht es wieder.
            x["status"], x["why"] = "wartet", f"Daten unvollständig: {bad}"
            ledger.note_error(state, symbol, f"Daten: {bad}")
            changed = True
            if clock.now_ts() >= window_end + 2 * config.BAR:
                x["done"] = True
                skip(x, f"Daten unvollständig: {bad}")
            continue
        pos = strategy.find_trigger(bars, x["high"], s["start"], c["window"])
        if pos is None:
            x["status"], x["why"] = "wartet", "Noch kein 5-Minuten-Schluss über dem Auslöser"
            changed = True
            if clock.now_ts() >= window_end:
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
        if data.bar_index(bars[-1], s["start"]) - data.bar_index(trig, s["start"]) > 1:
            skip(x, "Ausbruch verpasst, Bot lief zu spaet")
            continue
        last = bars[-1]["c"]
        p, why = strategy.plan(last * (1 + config.cost(c)), x["atr"], c)
        if not p:
            skip(x, why)
            continue
        order = dict(account="day", strategy=strategy.strategy_version(), side="BUY", symbol=symbol, type="market",
                     signalAt=clock.iso(trig["t"] + config.BAR), refPrice=round(last, 4), requestedQty=p["qty"])
        filled = config.fill_qty(p["qty"], bars[-1]["v"], c)
        if filled < 1:
            ledger.record_order(state, **order, filledQty=0, status="rejected", reason="Volumen der letzten Kerze zu klein")
            skip(x, "Volumen zu klein fuer eine Ausfuehrung")
            continue
        if filled < p["qty"]:
            p = dict(p, qty=filled, plannedRisk=round(filled * (p["entry"] - p["stop"]), 2))
        block = risk_engine.risk_block(state, "day", symbol, p["qty"], p["entry"], p["stop"], p["target"], last, s, c)
        if block:
            ledger.record_order(state, **order, filledQty=0, status="rejected", reason=block)
            skip(x, block)
            continue
        meta = result.get("meta", {})
        try:
            news = strategy.news_check(symbol, meta.get("longName") or meta.get("shortName") or "")
        except config.DATA_ERRORS as e:
            ledger.note_error(state, f"News {symbol}", e)
            skip(x, "News nicht abrufbar, Kauf ausgelassen")
            continue
        if news["flagged"]:
            skip(x, "News: " + news["flagged"][0])
            continue
        try:
            tm = strategy.time_machine(symbol, p, len(bars) - 1)
        except config.DATA_ERRORS:
            tm = None
        info = f"Time Machine: Stop zuerst {tm['stopFirst']:.0%}, Schnitt {tm['avgR']}R, Seed {tm['seed']}. " if tm else ""
        reason = (f"In Play: Volumen {x['rv']}x, Gap {x['gap']:.1%}, Ausbruch ueber {round(x['high'], 2)}, SPY im Plus. "
                  f"Stop {c['atr']} ATR, kein festes Ziel. {info}News: {news['recent']} Meldungen, keine schwere.")
        execution.buy(state, "day", symbol, p, "Yahoo 5m", reason)
        state["accounts"]["day"]["journal"][-1]["trigger"] = round(x["high"], 2)
        state["accounts"]["day"]["journal"][-1]["strategy"] = strategy.strategy_version()
        state["accounts"]["day"]["positions"][-1]["strategy"] = strategy.strategy_version()
        ledger.record_order(state, **order, executedAt=clock.iso(), filledQty=p["qty"], fillPrice=p["entry"],
                     costPerShare=round(p["entry"] - last, 4), fee=config.fee(p["qty"]),
                     status="filled" if p["qty"] == order["requestedQty"] else "partial", reason="Ausbruch",
                     risk={"stop": p["stop"], "plannedRisk": p["plannedRisk"]})
        x["status"], x["why"] = "gekauft", f"Gekauft zu {p['entry']}"
        ledger.decide(state, symbol, "gekauft", reason)
    return changed


def try_swing(state: State, s: Session, c: Config) -> bool:
    acc = state["accounts"]["swing"]
    if any(j["action"] == "BUY" for j in ledger.today_entries(acc)) or len(acc["positions"]) >= c["max_swing_open"]:
        return False
    changed = False
    for symbol in config.UNIVERSE:
        try:
            bars = data.session_bars(data.fetch(symbol, "5m", "1d"))
            if not bars or clock.now_ts() - bars[-1]["t"] > 900:
                continue
            last = bars[-1]["c"]
            p = strategy.daily_setup(symbol, last * (1 + config.cost(c)), c)
            if p:
                filled = config.fill_qty(p["qty"], bars[-1]["v"], c)
                p = dict(p, qty=filled, plannedRisk=round(filled * (p["entry"] - p["stop"]), 2)) if filled else None
        except config.DATA_ERRORS:
            continue
        if not p or risk_engine.risk_block(state, "swing", symbol, p["qty"], p["entry"], p["stop"], p["target"], last, s, c):
            continue
        try:
            news = strategy.news_check(symbol, "")
        except config.DATA_ERRORS as e:
            ledger.note_error(state, f"News {symbol}", e)
            continue
        if news["flagged"]:
            ledger.decide(state, symbol, "aussortiert", "Swing, News: " + news["flagged"][0])
            changed = True
            continue
        reason = f"Tages-Setup {p['setup']}, Stop am 10-Tage-Tief, Ziel 2R. News: {news['recent']} Meldungen, keine schwere."
        execution.buy(state, "swing", symbol, p, "Yahoo 5m", reason)
        state["accounts"]["swing"]["journal"][-1]["strategy"] = "swing-reclaim-1"
        state["accounts"]["swing"]["positions"][-1]["strategy"] = "swing-reclaim-1"
        ledger.record_order(state, account="swing", strategy="swing-reclaim-1", side="BUY", symbol=symbol, type="market",
                     signalAt=clock.iso(), executedAt=clock.iso(), refPrice=round(last, 4), requestedQty=p["qty"],
                     filledQty=p["qty"], fillPrice=p["entry"], costPerShare=round(p["entry"] - last, 4),
                     fee=config.fee(p["qty"]), status="filled", reason=p["setup"],
                     risk={"stop": p["stop"], "plannedRisk": p["plannedRisk"]})
        ledger.decide(state, symbol, "gekauft", reason)
        return True
    return changed


def tick(do_publish: bool = True) -> None:
    state = ledger.load()
    c = config.cfg()
    s = clock.session()
    changed = False
    del data.FETCH_LOG[:]
    problems = ledger.validate_state(state)
    if problems and not state.get("halt"):
        state["halt"] = {"at": clock.iso(), "reasons": problems}
    if state.get("halt"):
        state["status"] = "Not-Aus: " + "; ".join(state["halt"]["reasons"]) + ". Weiter erst nach Pruefung (paper.py resume)."
        ledger.save(state)
        print(clock.iso(), state["status"])
        return
    if s["open"]:
        changed |= manage(state, s, c)
        if s["noEntryBefore"] <= clock.now_ts() < s["noEntryAfter"]:
            if clock.now_ts() >= s["swingAfter"]:
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
    state["metrics"] = analytics.report(state)
    failed = [f["symbol"] for f in data.FETCH_LOG if not f["ok"]]
    state["dataQuality"] = {"at": clock.iso(), "source": "Yahoo chart v8", "requests": len(data.FETCH_LOG), "failed": len(failed),
                            "failedSymbols": sorted(set(failed))[:10],
                            "issues": [e for e in state.get("errors", []) if e["timestamp"][:10] == s["date"]][-5:]}
    ledger.recalc(state)
    last = state.get("publishedAt", 0)
    due = do_publish and (changed or (s["open"] and clock.now_ts() - last >= config.PUBLISH_EVERY))
    if due:
        state["publishedAt"] = clock.now_ts()
    ledger.save(state)
    if due:
        ok, out = publishing.publish()
        print("publish", ok, "" if ok else out)
    print(clock.iso(), state["status"], "changed" if changed else "")


def remember_bars(state: State, s: Session) -> None:
    """Kurse der Aktien mit Trades fuer die Ansicht im Dashboard: Tag in 5 Minuten, Swing in Tagen."""
    store = state.setdefault("bars", {})
    today = clock.ny().date().isoformat()
    day_syms = {p["symbol"] for p in state["accounts"]["day"]["positions"]}
    day_syms |= {j["symbol"] for j in state["accounts"]["day"]["journal"] if j["timestamp"][:10] == today}
    for symbol in day_syms:
        try:
            bars = data.session_bars(data.fetch(symbol, "5m", "1d"))
        except config.DATA_ERRORS:
            continue
        if bars:
            store[f"{clock.ny(bars[-1]['t']).date().isoformat()}:{symbol}"] = [[b["t"], round(b["c"], 2)] for b in bars]
    swing_syms = {p["symbol"] for p in state["accounts"]["swing"]["positions"]}
    swing_syms |= {j["symbol"] for j in state["accounts"]["swing"]["journal"][-6:]}
    for symbol in swing_syms:
        try:
            bars = data.rows(data.fetch(symbol, "1d", "6mo"), bar=86400)
        except config.DATA_ERRORS:
            continue
        store[f"D:{symbol}"] = [[b["t"], round(b["c"], 2)] for b in bars]
    for key in sorted(k for k in store if not k.startswith("D:"))[:-30]:
        del store[key]


def describe(state: State, s: Session, c: Config) -> None:
    """Was der Bot gerade tut und wann er das naechste Mal kaufen kann, fuer das Dashboard."""
    now = clock.now_ts()
    window_end = s["start"] + (1 + c["window"]) * config.BAR
    ip = state.get("inPlay", {})
    today = clock.ny().date().isoformat()
    waiting = [x["symbol"] for x in ip.get("symbols", []) if ip.get("date") == today and not x["done"]]
    buys = sum(1 for j in ledger.today_entries(state["accounts"]["day"]) if j["action"] == "BUY")
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
                (f"Offene Daytrades werden am Stop oder spätestens {clock.ny(s['flatBy']).strftime('%H:%M')} Uhr New York verkauft." if open_day
                 else "Der Bot wartet auf den nächsten Handelstag."))
    state["plan"] = {"phase": phase, "text": text, "next": clock.iso(nxt) if nxt else None,
                     "windowEnd": clock.iso(window_end), "dayBuys": buys, "maxDayTrades": c["max_day_trades"]}


def stats() -> Dict[str, Any]:
    state = ledger.load()
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
