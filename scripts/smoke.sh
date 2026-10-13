#!/usr/bin/env bash
# Production smoke tests: one Playwright test per definition of done (web/e2e/smoke.spec.ts),
# on the desktop and the phone project, one worker.
#
#   scripts/smoke.sh                 all 31, both projects
#   scripts/smoke.sh -g 'DoD-0[1-9]' extra arguments go to Playwright
#
# Settings and secrets are read from $PS_ENV_FILE, else ~/.secrets/portfoliosight.env:
# PS_BASE_URL (the site), PS_GATE_SECRET, PS_SHARE_TEST_RECIPIENT, PS_KS001_SSH_HOST,
# CLOUDFLARE_API_BASE, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, the two R2 keys and
# TIINGO_API_KEY. No host is spelled here. Output is redacted by the reporter; traces, video and
# HAR are off (web/playwright.config.ts).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${PS_ENV_FILE:-${HOME}/.secrets/portfoliosight.env}"
if [ ! -r "${env_file}" ]; then
  echo "cannot read the settings file ${env_file}; smoke tests not run" >&2
  exit 3
fi
set -a
# shellcheck disable=SC1090
. "${env_file}"
set +a

for name in PS_BASE_URL PS_GATE_SECRET; do
  if [ -z "${!name:-}" ]; then
    echo "${name} is missing from ${env_file}; smoke tests not run" >&2
    exit 3
  fi
done

export PS_SMOKE=1
unset PS_SMOKE_DRY_RUN
cd "${root}/web"
exec npx playwright test e2e/smoke.spec.ts --project chromium-desktop --project chromium-phone --workers 1 "$@"
