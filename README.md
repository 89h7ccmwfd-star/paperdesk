# Paperdesk

Nur Simulation mit je 10.000 USD virtuell (Daytrading und Swing). Keine Broker-Verbindung, keine echten Orders.

- `paper.py`: Scan, Entry, Exit, Time Machine, News, Budget, Risk nach der Doku des Trader-Skills, eigener Code
- `site/`: Dashboard und `state.json`; `config.json`: Parameter (die Analyse darf nur innerhalb von `BOUNDS` verstellen)
- Läufe: GitHub Actions (`.github/workflows/tick.yml`, `cloud-loop.sh`) zur Börsenzeit alle 5 Minuten, unabhängig von einem Rechner. Der Stand liegt in `site/state.json` im Repo.
- Dashboard: paperdesk-sim.pages.dev (Cloudflare Pages). Die Seite liest `site/state.json` direkt aus diesem Repo, GitHub cacht bis zu 5 Minuten. Nur Änderungen an der Seite selbst brauchen einen Upload.
- Abendanalyse: optionale lokale Claude-Aufgabe.

Strategie Daytrades: In-Play-Ausbruch (hohes Volumen im ersten 5-Minuten-Balken, Gap ab 0,5 %, Top 5), Kauf beim Schluss über dem Hoch des ersten Balkens in der ersten Stunde, nur wenn SPY im Plus ist. Stop 0,25 ATR, kein festes Ziel, Verkauf spätestens 15:55 ET. Swing: nur Rückeroberung des SMA20 im Aufwärtstrend, Zeitstopp nach 8 Wochen. Messung: `backtest.py` (alte Regel), `backtest2.py` (Varianten), `backtest2.py current` (aktualisiert `site/backtest.json`).

Annahmen: Gebühr 0,005 USD je Aktie (min. 1 USD), 99 große US-Aktien statt des ganzen Markts, max. 3 Daytrades am Tag, max. 50 USD Risiko je Trade, max. 3.000 USD je Position, max. 100 USD Tagesverlust. News sperren nur bei schweren Meldungen zum Unternehmen, die Time Machine ist reine Information. Nicht eingebaut: Broker, SEC-Daten, Kongress- und Investoren-Tracker, Steuern, Rebalancing.
