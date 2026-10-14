#!/usr/bin/env bash
# Mirror the R2 bucket portfoliosight-data to the laptop drive (spec 5.3).
#
#   r2_backup.sh            bucket -> /mnt/d/portfoliosight-data   (with --delete)
#   r2_backup.sh --restore  /mnt/d/portfoliosight-data -> bucket   (never --delete)
#
# The R2 keys are read as plain KEY=value lines from $PS_ENV_FILE, else from
# ~/.secrets/portfoliosight.env. With D: unmounted nothing runs and the exit status is 2.
# This file is self-contained: it sources nothing, so a copy installed elsewhere behaves the same.
set -euo pipefail

# cron's PATH is minimal; these are appended so a tool found earlier on PATH still wins.
PATH="${PATH}:/usr/local/bin:${HOME}/.local/bin"

MOUNT="/mnt/d"
MIRROR="${MOUNT}/portfoliosight-data"
BUCKET="s3://portfoliosight-data"
ENV_FILE="${PS_ENV_FILE:-${HOME}/.secrets/portfoliosight.env}"

mode="backup"
case "${1:-}" in
  "") ;;
  --restore) mode="restore" ;;
  *)
    echo "usage: r2_backup.sh [--restore]" >&2
    exit 64
    ;;
esac

if ! mountpoint -q "${MOUNT}"; then
  echo "D: drive is not mounted at ${MOUNT}; backup not run" >&2
  exit 2
fi

# The last KEY=value line for a name, without an "export " prefix or surrounding quotes.
read_setting() {
  local name="$1" line value=""
  while IFS= read -r line || [ -n "${line}" ]; do
    line="${line#export }"
    case "${line}" in
      "${name}="*) value="${line#"${name}="}" ;;
    esac
  done < "${ENV_FILE}"
  value="${value%$'\r'}"
  value="${value#\"}"; value="${value%\"}"
  value="${value#\'}"; value="${value%\'}"
  printf '%s' "${value}"
}

if [ ! -r "${ENV_FILE}" ]; then
  echo "cannot read the settings file ${ENV_FILE}; backup not run" >&2
  exit 3
fi
account="$(read_setting CLOUDFLARE_ACCOUNT_ID)"
key_id="$(read_setting CLOUDFLARE_R2_ACCESS_KEY_ID)"
secret="$(read_setting CLOUDFLARE_R2_SECRET_ACCESS_KEY)"
if [ -z "${account}" ] || [ -z "${key_id}" ] || [ -z "${secret}" ]; then
  echo "CLOUDFLARE_ACCOUNT_ID or the two R2 keys are missing from ${ENV_FILE}; backup not run" >&2
  exit 3
fi

mkdir -p "${MIRROR}"

endpoint="https://${account}.r2.cloudflarestorage.com"
if [ "${mode}" = "restore" ]; then
  sync_args=("${MIRROR}" "${BUCKET}")
else
  sync_args=("${BUCKET}" "${MIRROR}" --delete)
fi

AWS_ACCESS_KEY_ID="${key_id}" AWS_SECRET_ACCESS_KEY="${secret}" AWS_DEFAULT_REGION="auto" \
  aws s3 sync --endpoint-url "${endpoint}" "${sync_args[@]}"
