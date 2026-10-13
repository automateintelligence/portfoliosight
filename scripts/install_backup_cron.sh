#!/usr/bin/env bash
# Add the nightly R2 backup to the laptop's crontab, once (spec 5.3).
# Every other crontab line is left as it is; running this again changes nothing.
set -euo pipefail

# The line is written with a literal $HOME: cron expands it when the job runs.
# shellcheck disable=SC2016
CRON_LINE='30 5 * * * $HOME/programming/portfoliosight/scripts/r2_backup.sh >> $HOME/.local/state/portfoliosight/r2_backup.log 2>&1'

mkdir -p "${HOME}/.local/state/portfoliosight"

current="$(crontab -l 2>/dev/null || true)"
{
  if [ -n "${current}" ]; then
    # Only PortfolioSight's own entry is replaced; another project's r2_backup.sh line stays.
    printf '%s\n' "${current}" | grep -vF 'portfoliosight/scripts/r2_backup.sh' || true
  fi
  printf '%s\n' "${CRON_LINE}"
} | crontab -
