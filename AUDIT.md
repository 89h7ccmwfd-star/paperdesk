# Paperdesk: Systemaudit (Phase 1)

Stand 05.11.2026. Nur Simulation, keine Broker-Verbindung. Jeder Fund ist mit einer Reproduktion belegt, sonst steht „nicht belegt“ dabei.

## Architektur (Ist)

| Teil | Datei | Aufgabe |
|---|---|---|
| Daten | `paper.py` `curl`, `fetch`, `rows`, `session_bars` | Yahoo-Chart-JSON, nur abgeschlossene 5-Minuten-Kerzen |
| Strategie Tag | `paper.py` `day_context`, `rank_in_play`, `try_day` | In-Play-Liste, Ausbruch, Einstieg |
| Strategie Swing | `paper.py` `daily_setup`, `try_swing` | Rückeroberung SMA20 |
| Risiko | `paper.py` `plan`, `risk_block` | Größe, Limits |
| Ausführung | `paper.py` `buy`, `sell`, `manage` | Buchung, Stop, Tagesschluss |
| Zustand | `site/state.json`, `save` | atomar per `os.replace`, im Repo versioniert |
| Rückblick | `backtest.py`, `backtest2.py` | eigene, getrennte Regel-Implementierung |
| Betrieb | `cloud-loop.sh`, `.github/workflows/tick.yml` | GitHub Actions, Commit je Tick |
| Anzeige | `site/index.html` | liest `state.json` aus dem Repo |

## Funde, nach Schwere

| # | Schwere | Stelle | Problem | Beleg | Lösung | Test |
|---|---|---|---|---|---|---|
| 1 | kritisch | `cloud-loop.sh` Zeile 21, `paper.py` `try_day`/`manage`/`news_check` ohne Fehlerbehandlung | Ein einziger Yahoo-Fehler wirft eine Ausnahme, der Tick endet mit Fehlercode, der Lauf beendet sich für den Rest des Tages. Offene Daytrades werden dann nicht mehr verwaltet. | Code-Pfad: `fetch` wirft `RuntimeError`/`CalledProcessError`, kein `try`, `[ $code -ne 0 ] && exit` | Fehler je Aktie abfangen und protokollieren, Lauf bricht erst nach 6 Fehlern in Folge ab | `test_tick_survives_data_error` |
| 2 | hoch | `paper.py` `rank_in_play` | Fehlt der 9:30-Balken, gilt der 9:35-Balken als „erster Balken“. Auslöser und Volumen sind dann falsch. | Reproduktion: Liste ohne 9:30-Balken, `bars[0]` ist 9:35 | Erstbalken nur akzeptieren, wenn sein Zeitstempel der Börsenstart ist; Balkenindex aus der Zeit statt aus der Listenposition | `test_first_bar_must_be_open`, `test_trigger_uses_time_index` |
| 3 | hoch | `paper.py` `manage` | Der Balken, in dem gekauft wurde, wird beim Stop-Check übersprungen (`t >= openedAt`). Ein Stop in den ersten Minuten bleibt unbemerkt, Ergebnisse wirken zu gut. | Reproduktion: Kauf 9:41, Balken 9:40 mit Tief unter Stop wird ignoriert | Jeder Balken, der nach dem Kauf endet, zählt (vorsichtig: auch Minuten vor dem Kauf) | `test_stop_in_entry_bar` |
| 4 | hoch | `paper.py` `risk_block` | Tagesverlustgrenze zählt nur geschlossene Trades. Offene Verluste und offenes Risiko bis zum Stop bleiben unberücksichtigt. | Reproduktion: −600 $ offen, Grenze 500 $, neuer Kauf wird nicht gesperrt | Gebuchter Verlust plus Risiko aller offenen Daytrades plus neues Risiko muss unter der Grenze liegen; offene Verluste über der Grenze schließen alle Daytrades | `test_day_loss_counts_open_risk`, `test_day_loss_closes_positions` |
| 5 | hoch | `backtest2.py` `RISK`, `MAX_POS`, `SLIP` | Rückblick rechnet mit 50 $/3.000 $ und eigener Slippage, der Bot mit 250 $/5.000 $ aus `config.json` und ohne Slippage. Die Zahlen im Dashboard beschreiben nicht den laufenden Bot. | Reproduktion: Werte unterschiedlich | Rückblick liest Limits und Slippage aus derselben Konfiguration und nutzt dieselben Funktionen für Auslöser und Größe | `test_backtest_uses_live_rules` |
| 6 | hoch | `backtest2.py` `in_play` | Positionen werden unabhängig simuliert, ohne Bargeldgrenze und ohne Tagesverlustgrenze. | Code: keine Kassenprüfung | Gemeinsame Kasse je Tag, gleiche Sperren wie live | in `test_backtest_uses_live_rules` |
| 7 | mittel | `paper.py` `buy`/`sell` | Bot kauft und verkauft ohne Slippage, der Rückblick mit. | Reproduktion: Kauf zum letzten Schluss | Slippage aus `config.json` auf jede Ausführung | `test_slippage_applied` |
| 8 | mittel | `paper.py` `cfg` | Konfiguration wird ungeprüft übernommen (Tippfehler, negative Werte). | Code | Schema mit Typen und Bereichen, ungültig = Abbruch | `test_config_validation` |
| 9 | mittel | `cloud-loop.sh` `git pull --rebase || true` | Bei Konflikt (z. B. Abendanalyse schreibt gleichzeitig) bleibt ein halbfertiger Rebase liegen. | nicht reproduziert | Rebase bei Konflikt abbrechen, Commit des Bots behalten | offen |
| 10 | hoch (Statistik) | `backtest*.py` | Aktienliste von heute (Survivorship Bias), Yahoo liefert nachträglich korrigierte Volumen (live anders als im Rückblick, belegt am 04.11.: AMZN 6,0x gegen 3,6x). | belegt | Mit kostenlosen Daten nicht lösbar, nur dokumentieren; echter Test ist der laufende Papierhandel | – |
| 11 | hoch (Statistik) | Vorgehen | Über 900 Varianten getestet (480 + 288 + 144), die aktuelle Regel ist aus denselben 44 Tagen ausgewählt. Es gibt keinen unberührten Testzeitraum. | Protokoll in diesem Gespräch | Regel einfrieren, ab 06.11.2026 zählt nur der Papierhandel als Prüfung | – |
| 12 | mittel | `paper.py` | Keine Datenprüfung (doppelte Zeitstempel, unplausible OHLC, Lücken). | Code | Doppelte und unplausible Kerzen verwerfen und zählen | `test_bad_bars_dropped` |
| 13 | mittel | gesamt | Keine Tests. | `tests/` fehlte | Testsuite mit `unittest`, ohne Netz | diese Datei |
| 14 | niedrig | `rows` | Fehlender Kill-Switch bei Zustands- oder Datenproblemen. | Code | über Fund 1 und 4 teilweise; vollständiger Kill-Switch offen | offen |

## Behoben in diesem Schritt

Funde 1 bis 8, 12 und 13, jeweils mit Test in `tests/test_paper.py` (12 Tests, alle bestanden, ohne Netz: `python3 -m unittest discover -s tests`). Fund 9 teilweise: ein Rebase-Konflikt wird abgebrochen statt liegen zu bleiben, ungetestet.

Rückblick neu gerechnet mit denselben Funktionen und Limits wie der Bot (`backtest2.py current`, 03.09. bis 04.11.2026, 44 Tage): +751 USD bei 45 Trades, Trefferquote 37,8 %, größter Rückgang −319 USD. Erste Hälfte +345 USD, zweite +406 USD. Das ist kein Nachweis: Die Regel wurde an genau diesen Tagen ausgewählt (Fund 11), die Aktienliste ist von heute (Fund 10).

Nachgespielt am 05.11.2026 mit dem neuen Code: Tagesliste HD, CVS, AXP, LOW, TGT, kein Ausbruch, keine Fehler.

## Noch offen

Fund 9 (vollständig), 10, 14 und die Phasen 2, 3 (teilweise), 5 bis 12. Fund 11 (Mehrfachtests) ist mit research.py und dem eingefrorenen Holdout ab 06.11.2026 adressiert, rückwirkend aber nicht heilbar.

Vorher: Phasen 2 bis 12 des Auftrags: Datenversionierung, Börsenkalender, Order-Objekte mit Teilfüllungen und Ablehnungen, Walk-Forward-Pipeline mit Variantenprotokoll, Kennzahlen wie Sharpe und Sortino, Modulstruktur, Dashboard-Kennzeichnung von Rückblick und Papierhandel.

## Bewertung (ehrlich, Stand jetzt)

| Bereich | Note | Grund |
|---|---|---|
| Softwarequalität | 5/10 | eine Datei, jetzt mit Tests für die gefundenen Fehler, keine Modulstruktur |
| Datenqualität | 5/10 | Lücken- und Aktualitätsprüfung sperrt Entscheidungen, Abrufprotokoll, Tagesdaten archiviert (`data/`); Quelle bleibt kostenlos und inoffiziell |
| Backtest-Qualität | 5/10 | jetzt gleiche Regeln und Kasse wie live, aber Survivorship Bias und kurze Historie |
| Statistische Validität | 4/10 | Methodik jetzt vorhanden (Walk-Forward, Reality Check, Variantenprotokoll, eingefrorene Regel); Ergebnis: kein belegter Vorteil, siehe RESEARCH.md |
| Risikomanagement | 6/10 | Tagesverlust mit offenem Risiko, Kasse, Limits geprüft; keine Korrelationen |
| Paper-Execution | 6/10 | Order-Protokoll mit Zeitpunkten, Referenz- und Ausführungspreis, Kosten und Status; Spread (Annahme 0,04 %), Slippage, Gebühren, Volumengrenze 1 % der Kerze mit Teilausführung, Ablehnungen; keine echten Geld-Brief-Kurse, Limit-Orders nicht genutzt |
| Operative Zuverlässigkeit | 5/10 | eigener Börsenkalender (Feiertage, Halbtage) bis Ende 2027, Folgeläufe stoßen sich selbst an, Not-Aus bei kaputtem Zustand; der erste Start am Tag hängt weiter an GitHubs Zeitplan |

## Betrieb und Daten (Schritt 3)

- Börsenkalender in `paper.py` (`HOLIDAYS`, `EARLY_CLOSE`, laut nyse.com, gelesen 13.10.2026), gilt bis 31.12.2027 und bricht danach bewusst ab. Ersetzt die Sitzungszeiten von Yahoo.
- `check_bars`: fehlende oder mehr als eine Kerze verspätete Daten sperren die Entscheidung für diese Aktie und werden in `errors` protokolliert. Fehlt SPY, gibt es in diesem Lauf keine Daytrades.
- `dataQuality` im Zustand: Abrufe, Fehlschläge, betroffene Aktien, Probleme des Tages; das Dashboard zeigt es.
- `data/JJJJ-MM-TT.json`: Eingangsdaten der Tagesliste (Kontext je Aktie, Erstbalken, Auswahl) im Repo.
- `validate_state` und Not-Aus: Ist der Zustand ungültig, handelt der Bot nicht mehr und meldet den Grund, bis `paper.py resume` nach Prüfung aufgerufen wird.
- `cloud-loop.sh` stößt kurz vor Ende seiner Laufzeit selbst einen Folgelauf an (`gh workflow run`), wenn die Börse noch offen ist; wartet vor Börsenstart bis zu 3 Stunden, aber nur an Handelstagen.
- Tests: `tests/test_operations.py` (Kalender, Lücken, Verspätung, Sperre, Not-Aus), insgesamt 31 Tests bestanden.
- Ungetestet: der Folgelauf über `gh workflow run` in GitHub selbst, Halbtage im Live-Betrieb.

## Ausführung und Kennzahlen (Schritt 4)

- `paper.cost`: halber Spread (Annahme `spread` 0,04 %, Yahoo liefert keine Geld-Brief-Kurse) plus Slippage je Seite, live und im Rückblick gleich.
- `paper.fill_qty`: höchstens `max_volume_share` (1 %) des Volumens der Kerze; Rest verfällt (Teilausführung), unter einer Aktie wird abgelehnt.
- `state.orders`: jede Kauf- und Verkaufsorder mit ID, Strategie, Signal-, Erstell- und Ausführungszeit, Referenz- und Ausführungspreis, Kosten je Aktie, Gebühr, Status (`filled`, `partial`, `rejected`) und Grund; Ablehnungen durch Risiko oder Volumen ebenfalls.
- `analytics.py`: Netto, Rendite, Trefferquote, Ø Gewinn/Verlust, Gewinnfaktor, Erwartung mit 95-%-Intervall, Ø R, Sharpe, Sortino, max. Rückgang, Erholungsfaktor, Haltedauer, Zeit im Markt, Umschlag, Gebührenanteil, Spread- und Slippagekosten, je Monat und je Strategieversion. Fehlbuchungen werden herausgerechnet.
- Dashboard: Karte „Kennzahlen · Papierhandel“, klar getrennt von Rückblick und Walk-Forward.
- Neu gerechnet mit den Kosten: Rückblick +685 USD (45 Trades), Walk-Forward −34 USD, Reality Check p = 0,097, Zufallseinstieg −409 USD.
- Tests: 41 bestanden (neu: Volumengrenze, Spread, Order-Protokoll, Ablehnung, Kennzahlen mit Handrechnung).
- Nicht modelliert: Teilausführungen beim Verkauf (Stops gelten als voll ausgeführt), echte Geld-Brief-Spannen, Marktauswirkung über die Slippage hinaus.
