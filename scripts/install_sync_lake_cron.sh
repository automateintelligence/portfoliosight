#!/usr/bin/env bash
# Add the lake sync to the laptop's crontab, once (spec 5.4).
# Weekdays every 10 minutes from 07:00 to 09:50 (the laptop's clock is America/Los_Angeles):
# QSE's price stitch starts at 06:45, and the job syncs each lake run once, then no-ops.
# Every other crontab line is left as it is; running this again changes nothing.
set -euo pipefail

# The line is written with a literal $HOME: cron expands it when the job runs.
# shellcheck disable=SC2016
CRON_LINE='*/10 7-9 * * 1-5 $HOME/programming/portfoliosight/.venv/bin/python $HOME/programming/portfoliosight/scripts/sync_lake.py >> $HOME/.local/state/portfoliosight/sync_lake.log 2>&1'

mkdir -p "${HOME}/.local/state/portfoliosight"

current="$(crontab -l 2>/dev/null || true)"
{
  if [ -n "${current}" ]; then
    # Only PortfolioSight's own sync entry is replaced.
    printf '%s\n' "${current}" | grep -vF 'portfoliosight/scripts/sync_lake.py' || true
  fi
  printf '%s\n' "${CRON_LINE}"
} | crontab -
