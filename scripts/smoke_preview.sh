#!/usr/bin/env bash
# Private-preview smoke test (web/e2e/preview.spec.ts): the deployed Worker has preview on and
# gives nothing to a request without the gate secret. Never opens a keyed link.
#
# Settings and secrets are read from $PS_ENV_FILE, else ~/.secrets/portfoliosight.env:
# PS_BASE_URL, PS_GATE_SECRET, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${PS_ENV_FILE:-${HOME}/.secrets/portfoliosight.env}"
if [ ! -r "${env_file}" ]; then
  echo "cannot read the settings file ${env_file}; preview smoke test not run" >&2
  exit 3
fi
set -a
# shellcheck disable=SC1090
. "${env_file}"
set +a

for name in PS_BASE_URL PS_GATE_SECRET; do
  if [ -z "${!name:-}" ]; then
    echo "${name} is missing from ${env_file}; preview smoke test not run" >&2
    exit 3
  fi
done

export PS_SMOKE=1
unset PS_SMOKE_DRY_RUN
cd "${root}/web"
exec npx playwright test e2e/preview.spec.ts --project chromium-desktop --workers 1 "$@"
