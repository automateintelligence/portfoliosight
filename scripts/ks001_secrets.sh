#!/usr/bin/env bash
# Copy the keys the KS-001 container needs from the laptop env file to the host (spec 9.1).
#
#   ks001_secrets.sh [--host ALIAS]
#   ks001_secrets.sh --ensure-gate-secret
#
# Reads $PS_ENV_FILE, else ~/.secrets/portfoliosight.env. If the file has no PS_GATE_SECRET, one
# is generated (openssl rand -hex 24) and appended to it first. --ensure-gate-secret stops
# there: nothing leaves the laptop.
#
# Otherwise five keys (TIINGO_API_KEY, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_R2_ACCESS_KEY_ID,
# CLOUDFLARE_R2_SECRET_ACCESS_KEY, PS_GATE_SECRET) go to the host as plain KEY=value lines on
# ssh's stdin, into ~/.secrets/portfoliosight.env with mode 600. The mail keys and the share
# test recipient must be present on the laptop but are never copied. Only key names are printed.
#
# The host is --host, else PS_KS001_SSH_HOST from the environment, else from the env file.
set -euo pipefail

ENV_FILE="${PS_ENV_FILE:-${HOME}/.secrets/portfoliosight.env}"
HOST_KEYS=(TIINGO_API_KEY CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_R2_ACCESS_KEY_ID
  CLOUDFLARE_R2_SECRET_ACCESS_KEY PS_GATE_SECRET)
LAPTOP_ONLY_KEYS=(PS_SHARE_TEST_RECIPIENT MAILCHANNELS_API_KEY MAILCHANNELS_DKIM_PRIVATE_KEY)

usage() {
  echo "usage: ks001_secrets.sh [--host ALIAS] | --ensure-gate-secret" >&2
  exit 64
}

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

host="${PS_KS001_SSH_HOST:-}"
ensure_only=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --host)
      [ "$#" -ge 2 ] || usage
      host="$2"
      shift 2
      ;;
    --ensure-gate-secret)
      ensure_only=1
      shift
      ;;
    *) usage ;;
  esac
done

if [ ! -r "${ENV_FILE}" ]; then
  echo "the env file is missing or unreadable; nothing done" >&2
  exit 3
fi

if [ -z "$(read_setting PS_GATE_SECRET)" ]; then
  generated="$(openssl rand -hex 24)"
  if ! [[ "${generated}" =~ ^[0-9a-f]{48}$ ]]; then
    echo "could not generate PS_GATE_SECRET; nothing done" >&2
    exit 1
  fi
  # Start on a new line even when the file does not end with one.
  if [ -s "${ENV_FILE}" ] && [ -n "$(tail -c 1 "${ENV_FILE}")" ]; then
    printf '\n' >> "${ENV_FILE}"
  fi
  printf 'PS_GATE_SECRET=%s\n' "${generated}" >> "${ENV_FILE}"
  unset generated
  echo "PS_GATE_SECRET generated and added to the laptop env file"
else
  echo "PS_GATE_SECRET already present in the laptop env file"
fi
[ "${ensure_only}" = 0 ] || exit 0

missing=()
for key in "${HOST_KEYS[@]}" "${LAPTOP_ONLY_KEYS[@]}"; do
  [ -n "$(read_setting "${key}")" ] || missing+=("${key}")
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "missing in the laptop env file: ${missing[*]}; nothing copied" >&2
  exit 3
fi

[ -n "${host}" ] || host="$(read_setting PS_KS001_SSH_HOST)"
if [ -z "${host}" ]; then
  echo "PS_KS001_SSH_HOST (or --host) must be set; nothing copied" >&2
  exit 3
fi

# The values travel on stdin only; the remote command line holds no value.
# shellcheck disable=SC2016  # ~ is meant to expand on the host
for key in "${HOST_KEYS[@]}"; do
  printf '%s=%s\n' "${key}" "$(read_setting "${key}")"
done | ssh "${host}" 'umask 077 && mkdir -p ~/.secrets && cat > ~/.secrets/portfoliosight.env && chmod 600 ~/.secrets/portfoliosight.env'

echo "copied to the host: ${HOST_KEYS[*]}"
