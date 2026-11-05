# Statistische Prüfung der Daytrade-Regel

Stand 05.11.2026, `research.py`, Ergebnis in `research/report.json`, jede gerechnete Variante in `research/variants.jsonl`.
Daten: Yahoo, 5-Minuten-Kerzen, 44 Handelstage (03.09. bis 04.11.2026), 98 Aktien von heutiger Liste.

## Ergebnis in einem Satz

**Ein Vorteil der Regel ist statistisch nicht belegt.** Außerhalb der Auswahltage (Walk-Forward) liegt sie bei etwa null.

## Zahlen

| Prüfung | Ergebnis | Bedeutung |
|---|---|---|
| Eingefrorene Regel, alle 44 Tage | +751 USD, 45 Trades, Schnitt +0,41 R (95 %: −0,18 bis +1,08) | an denselben Tagen ausgewählt, daher zu gut |
| **Walk-Forward** (20 Tage auswählen, 6 Tage prüfen, 4 Abschnitte) | **−2,90 USD** an 24 Testtagen, Tagesschnitt 95 %: −17,72 bis +18,35 | der einzige faire Test mit diesen Daten: kein Vorteil erkennbar |
| Reality Check (White) über 72 Varianten | p = 0,08 | nicht signifikant; mit den rund 940 früher getesteten Varianten wäre p noch höher |
| Zufälliger Einstieg, sonst gleiche Regeln | −277 USD | der Ausbruch schlägt Zufall in dieser Stichprobe |
| SPY Eröffnung bis Schluss, 5.000 USD | −318 USD | einfacher Vergleich am selben Zeitraum |
| Tage mit steigendem SPY (21) | +824 USD, Schnitt +0,78 R | fast der ganze Gewinn |
| Tage mit fallendem SPY (23) | −74 USD, Schnitt −0,02 R | kein Vorteil |

Empfindlichkeit (je ein Parameter geändert, alle 44 Tage): Top 3 +970, Top 8 +275, Stop 0,2 ATR +772, Stop 0,3 ATR +571, Volumen 1,25x +617, Gap 0,3 % +687, Ziel 1R +62 USD. Ein festes Ziel schadet in jeder Rechnung, die übrigen Nachbarn liegen in derselben Größenordnung.

## Was daraus folgt

1. Die Regel bleibt unverändert (`research/freeze.json`, Version `inplay-1`). Jeder Kauf trägt diese Version.
2. Ab 06.11.2026 zählt nur der Papierhandel als unberührter Test. Eine Aussage ist frühestens nach etwa 40 Trades möglich.
3. Parameter werden bis dahin nicht nachgestellt. Jede Änderung braucht eine neue Version und beginnt den Test von vorn.

## Grenzen

Kostenlose Daten mit nachträglichen Korrekturen, Aktienliste von heute, nur 60 Tage 5-Minuten-Historie bei Yahoo, Walk-Forward mit nur 4 Abschnitten. Mehr Historie bräuchte eine kostenpflichtige Datenquelle.
