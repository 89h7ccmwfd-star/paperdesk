#!/bin/bash
# Ein Lauf in GitHub Actions: tickt kurz nach jedem 5-Minuten-Balken und sichert den Stand im Repo.
set -u
git config user.name "paperdesk-bot"
git config user.email "paperdesk-bot@users.noreply.github.com"
# Ein Lauf bleibt bis Boersenschluss (hoechstens 350 Minuten), weitere geplante Starts warten solange.
end=$(( $(date +%s) + 350 * 60 ))
fails=0
while :; do
  git pull --rebase --quiet || git rebase --abort 2>/dev/null || true
  out=$(python3 paper.py tick 2>&1); code=$?
  echo "$out"
  case "$out" in
    *"Markt geschlossen"*changed*) ;;
    *"Markt geschlossen"*) git checkout -- site/state.json; exit "$code";;
  esac
  git add site/state.json
  [ -d data ] && git add data
  [ -f config.json ] && git add config.json
  if ! git diff --cached --quiet; then
    git commit --quiet -m "Stand $(date -u +%H:%M)" && { git push --quiet || { git pull --rebase --quiet && git push --quiet; }; }
  fi
  # Datenfehler beenden den Lauf nicht sofort; erst sechs Fehler in Folge.
  if [ $code -ne 0 ]; then fails=$((fails + 1)); [ $fails -ge 6 ] && exit $code; else fails=0; fi
  case "$out" in *"Markt geschlossen"*)
    wait=$(python3 -c "import paper, time; s = paper.session(); print(int(s['start'] - time.time()) if s['trading'] and s['start'] > time.time() else -1)" 2>/dev/null || echo -1)
    if [ "$wait" -gt 0 ] && [ "$wait" -lt 10800 ]; then echo "Warte $wait s auf Boersenstart"; sleep "$wait"; end=$(( $(date +%s) + 350 * 60 )); continue; fi
    exit 0;;
  esac
  now=$(date +%s)
  next=$(( now - now % 300 + 360 ))
  if [ $next -ge $end ]; then
    # Laufzeit fast aufgebraucht, Boerse noch offen: Folgelauf selbst anstossen statt auf GitHubs Zeitplan zu warten.
    gh workflow run tick.yml --ref main && echo "Folgelauf angestossen"
    exit 0
  fi
  sleep $(( next - now ))
done
