#!/usr/bin/env bash
# Deploy one commit of PortfolioSight to KS-001 and check its health (spec 9.1).
#
#   deploy_ks001.sh [--host ALIAS] [--install-timer] <sha>
#
# On the host, over ssh: fetch, check out <sha>, write deploy/.env (GIT_SHA=<sha>), build the
# tagged image, start `api`, then ask the service for its health. Rollback is the same command
# with the previous sha. --install-timer also renders and enables the nightly systemd timer.
#
# Settings are plain KEY=value lines in $PS_ENV_FILE, else ~/.secrets/portfoliosight.env; a
# variable already in the environment wins:
#   PS_KS001_SSH_HOST  ssh alias of the host (or --host)
#   PS_HEALTH_URL      the health address as seen from the host
# The gate secret is read on the host from the host's own env file and reaches curl on stdin;
# it is never on a command line and never crosses the ssh connection.
set -euo pipefail

ENV_FILE="${PS_ENV_FILE:-${HOME}/.secrets/portfoliosight.env}"

usage() {
  echo "usage: deploy_ks001.sh [--host ALIAS] [--install-timer] <sha>" >&2
  exit 64
}

# The last KEY=value line for a name, without an "export " prefix or surrounding quotes.
read_setting() {
  local name="$1" line value=""
  [ -r "${ENV_FILE}" ] || return 0
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
health_url="${PS_HEALTH_URL:-}"
install_timer=0
sha=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --host)
      [ "$#" -ge 2 ] || usage
      host="$2"
      shift 2
      ;;
    --install-timer)
      install_timer=1
      shift
      ;;
    -*) usage ;;
    *)
      [ -z "${sha}" ] || usage
      sha="$1"
      shift
      ;;
  esac
done

[[ "${sha}" =~ ^[0-9a-f]{7,40}$ ]] || usage
[ -n "${host}" ] || host="$(read_setting PS_KS001_SSH_HOST)"
[ -n "${health_url}" ] || health_url="$(read_setting PS_HEALTH_URL)"
if [ -z "${host}" ] || [ -z "${health_url}" ]; then
  echo "PS_KS001_SSH_HOST (or --host) and PS_HEALTH_URL must be set; deploy not run" >&2
  exit 3
fi

# The remote script arrives on stdin; its three arguments are quoted for the remote shell.
remote_args="$(printf '%q ' "${sha}" "${health_url}" "${install_timer}")"
# shellcheck disable=SC2029  # the arguments are meant to expand on this side
ssh "${host}" "bash -s -- ${remote_args}" <<'REMOTE'
set -euo pipefail
sha="$1"
health_url="$2"
install_timer="$3"
compose="deploy/docker-compose.yml"
env_file="${HOME}/.secrets/portfoliosight.env"

cd "${HOME}/portfoliosight"
git fetch github
git checkout --detach "${sha}"
printf 'GIT_SHA=%s\n' "${sha}" > deploy/.env
docker compose -f "${compose}" build
docker compose -f "${compose}" up -d api

if [ "${install_timer}" = 1 ]; then
  sed -e "s|__USER__|${USER}|g" -e "s|__HOME__|${HOME}|g" \
    deploy/systemd/portfoliosight-nightly.service.in \
    | sudo tee /etc/systemd/system/portfoliosight-nightly.service > /dev/null
  sudo cp deploy/systemd/portfoliosight-nightly.timer /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now portfoliosight-nightly.timer
fi

# The header goes to curl on stdin (-H @-), so the secret is in no process's arguments.
gate_header() {
  local line value=""
  while IFS= read -r line || [ -n "${line}" ]; do
    line="${line#export }"
    case "${line}" in
      PS_GATE_SECRET=*) value="${line#PS_GATE_SECRET=}" ;;
    esac
  done < "${env_file}"
  printf 'x-ps-gate: %s\n' "${value}"
}

for attempt in $(seq 1 30); do
  if gate_header | curl -fsS -o /dev/null --max-time 10 -H @- "${health_url}" 2> /dev/null; then
    echo "portfoliosight ${sha} is healthy on $(hostname)"
    exit 0
  fi
  sleep 2
done
echo "portfoliosight ${sha} did not become healthy; see: docker logs portfoliosight-api" >&2
exit 1
REMOTE
