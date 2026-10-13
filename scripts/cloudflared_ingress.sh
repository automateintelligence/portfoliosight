#!/usr/bin/env bash
# Add the PortfolioSight API hostname to the cloudflared ingress on the host, or undo it
# (spec 9.2). Runs ON the host that runs cloudflared.
#
#   cloudflared_ingress.sh install
#   cloudflared_ingress.sh rollback <backup file>
#
# install:
#   1. reads the live config and notes the HTTPS status of every hostname already in it;
#   2. writes a candidate BESIDE the live file (<config>.new.XXXXXX, a name of its own) with
#      one new rule above the catch-all; every existing line is carried over unchanged;
#   3. validates the candidate with cloudflared; a refusal ends here, the live file untouched;
#   4. copies the live file to <config>.bak-<UTC time>, renames the candidate over the live
#      file (mv, same directory) and restarts cloudflared;
#   5. checks that every hostname noted in step 1 answers with the status noted there.
#   A failed restart or check puts the backup back by the same rename, restarts cloudflared
#   again and exits non-zero. A rule already present for the hostname with the same service
#   means there is nothing to do; with another service it is an error and nothing is changed.
#
# rollback: puts the named backup back by the same rename and restarts cloudflared.
#
# Settings (environment):
#   PS_API_SERVICE_URL         the service address of the new rule (required for install)
#   PS_API_HOSTNAME            the new hostname (default api.portfoliosight.ai)
#   PS_CLOUDFLARED_CONFIG      the live config (default /etc/cloudflared/config.yml)
#   PS_CLOUDFLARED_UNIT        the systemd unit (default cloudflared)
#   PS_INGRESS_CHECK_ATTEMPTS  tries per hostname after the restart (default 12)
#   PS_INGRESS_CHECK_SLEEP     seconds between tries (default 5)
#   PS_INGRESS_ALLOW_UNREACHABLE  set to 1 to go on when a hostname already in the config gives
#                              no HTTP answer at all before the change (it is then not checked
#                              afterwards); by default such a hostname stops the install
# When the config or its directory is not writable the script runs itself again under sudo.
# One run at a time: a lock is held on the config's directory, and the only file a run ever
# removes is the candidate it created itself.
set -euo pipefail

CONFIG="${PS_CLOUDFLARED_CONFIG:-/etc/cloudflared/config.yml}"
NEW_HOST="${PS_API_HOSTNAME:-api.portfoliosight.ai}"
SERVICE_URL="${PS_API_SERVICE_URL:-}"
UNIT="${PS_CLOUDFLARED_UNIT:-cloudflared}"
ATTEMPTS="${PS_INGRESS_CHECK_ATTEMPTS:-12}"
PAUSE="${PS_INGRESS_CHECK_SLEEP:-5}"
ALLOW_UNREACHABLE="${PS_INGRESS_ALLOW_UNREACHABLE:-0}"
CANDIDATE=""

usage() {
  echo "usage: cloudflared_ingress.sh install | rollback <backup file>" >&2
  exit 64
}

fail() {
  echo "cloudflared_ingress: $*" >&2
  exit 1
}

# Prints, for the ingress list of a config file:
#   HOST <hostname>            one line per rule that has a hostname
#   OURS <service>             when a rule for $NEW_HOST exists
#   CATCHALL <line> <indent>   the first line and indentation of the last rule, when that rule
#                              has a service and no hostname
# Only `hostname:` and `service:` keys of the list items themselves are read.
scan_ingress() {
  awk -v ours="${NEW_HOST}" '
    function value(text) {
      sub(/^[^:]*:[ \t]*/, "", text)
      sub(/[ \t]+#.*$/, "", text)
      sub(/[ \t\r]+$/, "", text)
      if (text ~ /^".*"$/ || text ~ /^\047.*\047$/) text = substr(text, 2, length(text) - 2)
      return text
    }
    function key(text) {
      if (text ~ /^hostname:/) host[n] = value(text)
      else if (text ~ /^service:/) service[n] = value(text)
    }
    /^ingress:[ \t\r]*(#.*)?$/ { inside = 1; next }
    inside && /^[^ \t#-]/ { inside = 0 }
    !inside { next }
    match($0, /^[ \t]*- /) {
      indent = substr($0, 1, RLENGTH - 2)
      if (n == 0) item_indent = indent
      if (indent == item_indent) {
        n++; start[n] = NR; host[n] = ""; service[n] = ""
        key(substr($0, RLENGTH + 1))
        next
      }
    }
    n > 0 && match($0, /^[ \t]*/) && RLENGTH == length(item_indent) + 2 { key(substr($0, RLENGTH + 1)) }
    END {
      for (i = 1; i <= n; i++) {
        if (host[i] != "") print "HOST " host[i]
        if (host[i] == ours) print "OURS " service[i]
      }
      if (n > 0 && host[n] == "" && service[n] != "") print "CATCHALL " start[n] " " item_indent "|"
    }
  ' "$1"
}

# The HTTP status of a hostname, or "none" when there was no HTTP answer at all.
status_of() {
  local url code
  url="$(printf '%s://%s/' https "$1")"
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${url}")" || code="none"
  [[ "${code}" =~ ^[1-5][0-9][0-9]$ ]] || code="none"
  printf '%s' "${code}"
}

# A file of this run's own beside the live file, removed when the run ends.
make_candidate() {
  CANDIDATE="$(mktemp "${CONFIG}.new.XXXXXX")" || fail "cannot stage a file beside ${CONFIG}"
  trap 'rm -f "${CANDIDATE}"' EXIT
}

# Copies a backup beside the live file and renames it over the live file, then restarts.
# Returns 2 when the file could not be put back (no restart is attempted), 3 when it was put
# back but the restart failed. Written with explicit checks: callers test its status, which
# switches errexit off inside it.
restore() {
  [ -n "${CANDIDATE}" ] || make_candidate
  cp -p "$1" "${CANDIDATE}" || return 2
  mv -f "${CANDIDATE}" "${CONFIG}" || return 2
  systemctl restart "${UNIT}" || return 3
}

# Says what a failed restore left behind, and exits.
restore_failed() {
  if [ "$1" = 2 ]; then
    fail "$2 could NOT be put back; ${CONFIG} is as it was before this restore and ${UNIT} was not restarted: act now"
  fi
  fail "$2 is back in place but ${UNIT} did not restart: act now"
}

[ "$#" -ge 1 ] || usage
command="$1"
case "${command}" in
  install) [ "$#" -eq 1 ] || usage ;;
  rollback) [ "$#" -eq 2 ] || usage ;;
  *) usage ;;
esac

if [ "${command}" = install ]; then
  # One plain URL: it becomes a YAML scalar, so no space, quote or comment sign.
  [[ "${SERVICE_URL}" =~ ^[a-z][a-z0-9+.-]*://[A-Za-z0-9._:/-]+$ ]] \
    || fail "PS_API_SERVICE_URL must be set to one plain URL; nothing changed"
fi
[[ "${NEW_HOST}" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]] || fail "PS_API_HOSTNAME is not a host name"
[ -f "${CONFIG}" ] || fail "${CONFIG} does not exist; nothing changed"

if [ "$(id -u)" -ne 0 ] && { [ ! -w "${CONFIG}" ] || [ ! -w "$(dirname "${CONFIG}")" ]; }; then
  exec sudo env \
    "PS_CLOUDFLARED_CONFIG=${CONFIG}" "PS_API_HOSTNAME=${NEW_HOST}" \
    "PS_CLOUDFLARED_UNIT=${UNIT}" "PS_INGRESS_CHECK_ATTEMPTS=${ATTEMPTS}" \
    "PS_INGRESS_CHECK_SLEEP=${PAUSE}" "PS_API_SERVICE_URL=${SERVICE_URL}" \
    "PS_INGRESS_ALLOW_UNREACHABLE=${ALLOW_UNREACHABLE}" \
    bash "$0" "$@"
fi

exec 9< "$(dirname "${CONFIG}")"
flock -n 9 || fail "another run holds the lock on $(dirname "${CONFIG}"); nothing changed"

if [ "${command}" = rollback ]; then
  backup="$2"
  case "${backup}" in
    "${CONFIG}.bak-"*) ;;
    *) fail "not a backup of ${CONFIG}: nothing changed" ;;
  esac
  [ -f "${backup}" ] || fail "${backup} does not exist; nothing changed"
  restore "${backup}" || restore_failed "$?" "${backup}"
  echo "restored ${backup} and restarted ${UNIT}"
  exit 0
fi

scan="$(scan_ingress "${CONFIG}")"
catch_all="$(printf '%s\n' "${scan}" | sed -n 's/^CATCHALL //p')"
[ -n "${catch_all}" ] \
  || fail "no ingress list ending in a catch-all rule was found in ${CONFIG}; nothing changed"
catch_line="${catch_all%% *}"
indent="${catch_all#* }"
indent="${indent%|}"

if printf '%s\n' "${scan}" | grep -q '^OURS '; then
  current="$(printf '%s\n' "${scan}" | sed -n 's/^OURS //p' | head -n 1)"
  if [ "${current}" = "${SERVICE_URL}" ]; then
    echo "the rule for ${NEW_HOST} is already installed; nothing changed"
    exit 0
  fi
  fail "${NEW_HOST} already has a rule with another service; nothing changed"
fi

# The baseline: every hostname already served (wildcards cannot be asked for).
hosts=()
baseline=()
while IFS= read -r existing; do
  case "${existing}" in '' | *'*'*) continue ;; esac
  before="$(status_of "${existing}")"
  if [ "${before}" = none ]; then
    # Without an answer now there is nothing to compare with afterwards.
    [ "${ALLOW_UNREACHABLE}" = 1 ] \
      || fail "${existing} gives no HTTP answer now, so the change could not be checked; nothing changed (PS_INGRESS_ALLOW_UNREACHABLE=1 leaves it out)"
    echo "before: ${existing} gives no HTTP answer; left out of the check"
    continue
  fi
  hosts+=("${existing}")
  baseline+=("${before}")
  echo "before: ${existing} answers ${before}"
done < <(printf '%s\n' "${scan}" | sed -n 's/^HOST //p')

# The candidate starts as a copy so that it has the live file's owner and mode.
make_candidate
cp -p "${CONFIG}" "${CANDIDATE}"
awk -v at="${catch_line}" -v indent="${indent}" -v host="${NEW_HOST}" -v service="${SERVICE_URL}" '
  NR == at { print indent "- hostname: " host; print indent "  service: " service }
  { print }
' "${CONFIG}" > "${CANDIDATE}"

cloudflared tunnel --config "${CANDIDATE}" ingress validate \
  || fail "cloudflared refused the candidate; the live config was not touched"

backup="${CONFIG}.bak-$(date -u +%Y%m%dT%H%M%SZ)"
[ ! -e "${backup}" ] || backup="${backup}-$$"
cp -p "${CONFIG}" "${backup}"
mv -f "${CANDIDATE}" "${CONFIG}"

undo() {
  echo "cloudflared_ingress: $1; restoring ${backup}" >&2
  restore "${backup}" || restore_failed "$?" "${backup}"
  fail "the previous config is back in place and ${UNIT} was restarted"
}

systemctl restart "${UNIT}" || undo "${UNIT} did not restart"

for index in "${!hosts[@]}"; do
  after=""
  for _ in $(seq 1 "${ATTEMPTS}"); do
    after="$(status_of "${hosts[${index}]}")"
    [ "${after}" != "${baseline[${index}]}" ] || break
    sleep "${PAUSE}"
  done
  if [ "${after}" != "${baseline[${index}]}" ]; then
    undo "${hosts[${index}]} answered ${after}, before the change ${baseline[${index}]}"
  fi
  echo "after: ${hosts[${index}]} answers ${after}"
done

echo "installed the rule for ${NEW_HOST}; backup: ${backup}"
