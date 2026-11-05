#!/bin/bash
# Ein Lauf in GitHub Actions: tickt kurz nach jedem 5-Minuten-Balken und sichert den Stand im Repo.
set -u
git config user.name "paperdesk-bot"
git config user.email "paperdesk-bot@users.noreply.github.com"
end=$(( $(date +%s) + 28 * 60 ))
while :; do
  git pull --rebase --quiet || true
  out=$(python3 paper.py tick 2>&1); code=$?
  echo "$out"
  case "$out" in
    *"Markt geschlossen"*changed*) ;;
    *"Markt geschlossen"*) git checkout -- site/state.json; exit "$code";;
  esac
  git add site/state.json
  [ -f config.json ] && git add config.json
  if ! git diff --cached --quiet; then
    git commit --quiet -m "Stand $(date -u +%H:%M)" && { git push --quiet || { git pull --rebase --quiet && git push --quiet; }; }
  fi
  [ $code -ne 0 ] && exit $code
  case "$out" in *"Markt geschlossen"*) exit 0;; esac
  now=$(date +%s)
  next=$(( now - now % 300 + 360 ))
  [ $next -ge $end ] && exit 0
  sleep $(( next - now ))
done
