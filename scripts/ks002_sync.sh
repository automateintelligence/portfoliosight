#!/usr/bin/env bash
# Copy the fixed-risk experiment to KS-002 and bring job directories back (protocol §8 "Setup").
#
#   scripts/ks002_sync.sh push SNAPSHOT_DIR      rsync the worktree and the snapshot, build the venv
#   scripts/ks002_sync.sh venv SNAPSHOT_NAME     (re)build only the venv from that snapshot's lock
#   scripts/ks002_sync.sh pull RUN_DIR [JOB...]  rsync job directories (and parent.json) back
#
# Target: ~/fr-experiment/ on `ssh KS-002-jeff` (override with KS_HOST / KS_DIR).
#   ~/fr-experiment/repo         the worktree (no .venv, caches, .git objects of other branches)
#   ~/fr-experiment/snapshots/   the frozen snapshot (read-only, hashes verified after the copy)
#   ~/fr-experiment/venv         Python venv: the snapshot's dependency lock, then `pip install -e .`
#   ~/fr-experiment/runs/        run directories (pull copies them back to the same relative path)
# Run the job there with:
#   ssh KS-002-jeff 'cd ~/fr-experiment/repo && OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
#     MKL_NUM_THREADS=1 ~/fr-experiment/venv/bin/python -m portfoliosight.research.fixedrisk.cli \
#     run --run-dir ~/fr-experiment/runs/RUN --menu M --engine E --snapshot ~/fr-experiment/snapshots/NAME'
set -euo pipefail

HOST="${KS_HOST:-KS-002-jeff}"
DIR="${KS_DIR:-fr-experiment}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RSYNC=(rsync -az --delete)

excludes=(
  --exclude '.venv/' --exclude 'venv/' --exclude '__pycache__/' --exclude '*.pyc'
  --exclude '.pytest_cache/' --exclude '.ruff_cache/' --exclude '.mypy_cache/' --exclude '.pyright/'
  --exclude 'node_modules/' --exclude '.worktrees/' --exclude 'web/' --exclude '*.egg-info/'
  --exclude 'graphify-out/cache/' --exclude '.git/'
)

push_repo() {
  ssh "$HOST" "mkdir -p ~/$DIR/repo ~/$DIR/snapshots ~/$DIR/runs"
  "${RSYNC[@]}" "${excludes[@]}" "$REPO/" "$HOST:$DIR/repo/"
  # the freeze/verify scripts read the git HEAD only at freeze time; record it for the run
  git -C "$REPO" rev-parse HEAD | ssh "$HOST" "cat > ~/$DIR/repo/GIT_HEAD"
}

push_snapshot() {
  local snap name
  snap="$(cd "$1" && pwd)"
  name="$(basename "$snap")"
  [ -f "$snap/snapshot.json" ] || { echo "not a snapshot: $snap" >&2; exit 2; }
  # A snapshot is read-only and immutable: copy it once; an existing copy is only verified.
  if ssh "$HOST" "test -f ~/$DIR/snapshots/$name/snapshot.json"; then
    echo "snapshot $name already on $HOST"
  else
    rsync -a "$snap" "$HOST:$DIR/snapshots/"
  fi
}

verify_snapshot() {
  local name
  name="$(basename "$(cd "$1" && pwd)")"
  ssh "$HOST" "cd ~/$DIR/repo && ~/$DIR/venv/bin/python scripts/freeze_fixed_risk_inputs.py --verify ~/$DIR/snapshots/$name"
}

make_venv() {
  # Recreate the environment from the dependency lock of snapshot NAME: "name==version" lines
  # only; comment lines and the editable project line are skipped.
  local name="$1"
  ssh "$HOST" bash -s "$DIR" "$name" <<'REMOTE'
set -euo pipefail
DIR="$1"; NAME="$2"
cd ~/"$DIR"
python3 -m venv venv
venv/bin/python -m pip install -q --upgrade pip
lock="snapshots/$NAME/environment/dependency_lock.txt"
grep -E '^[A-Za-z0-9_.-]+==' "$lock" | grep -viE '^(portfoliosight|qse)==' > /tmp/fr-lock.txt
venv/bin/python -m pip install -q -r /tmp/fr-lock.txt
venv/bin/python -m pip install -q --no-deps -e repo
venv/bin/python - <<'PY'
import numpy, scipy, pandas, pyarrow, cvxpy, arch, exchange_calendars, threadpoolctl
print("venv ok: numpy", numpy.__version__, "scipy", scipy.__version__, "pandas", pandas.__version__)
PY
REMOTE
}

pull() {
  local run="$1"; shift
  local rel
  rel="$(basename "$run")"
  mkdir -p "$run"
  if [ "$#" -eq 0 ]; then
    rsync -az "$HOST:$DIR/runs/$rel/" "$run/" --exclude 'host.lock' --exclude 'ledger_cache/'
  else
    for job in "$@"; do
      rsync -az "$HOST:$DIR/runs/$rel/$job/" "$run/$job/"
    done
  fi
}

case "${1:-}" in
  push)
    [ "$#" -eq 2 ] || { echo "usage: $0 push SNAPSHOT_DIR" >&2; exit 2; }
    push_repo
    push_snapshot "$2"
    make_venv "$(basename "$(cd "$2" && pwd)")"
    verify_snapshot "$2"
    ;;
  venv)
    [ "$#" -eq 2 ] || { echo "usage: $0 venv SNAPSHOT_NAME" >&2; exit 2; }
    make_venv "$2"
    ;;
  pull)
    [ "$#" -ge 2 ] || { echo "usage: $0 pull RUN_DIR [JOB...]" >&2; exit 2; }
    shift
    pull "$@"
    ;;
  *) echo "usage: $0 push SNAPSHOT_DIR | venv SNAPSHOT_NAME | pull RUN_DIR [JOB...]" >&2; exit 2 ;;
esac
