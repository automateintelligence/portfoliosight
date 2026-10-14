# Deploy PortfolioSight.
#
#   make deploy-frontend   build the page and deploy the Cloudflare Worker
#   make deploy-backend    deploy the API container on KS-001 at the current commit
#   make deploy            backend first, then frontend (the page needs the API it was built for)
#   make smoke             production smoke tests (scripts/smoke.sh)
#
# Settings and secrets come from ~/.secrets/portfoliosight.env (override with PS_ENV_FILE=...).
# The backend deploys a commit, not your working tree: KS-001 fetches it from GitHub, so it must
# be committed and pushed. SHA=<commit> deploys another one (for example, to roll back).

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
PS_ENV_FILE ?= $(HOME)/.secrets/portfoliosight.env
SHA ?= $(shell git rev-parse HEAD)
LOAD_ENV = set -a; . "$(PS_ENV_FILE)"; set +a

.PHONY: deploy deploy-frontend deploy-backend smoke check-pushed

deploy: deploy-backend deploy-frontend

deploy-frontend:
	$(LOAD_ENV); cd web && npm ci --silent && npm run build && npx wrangler deploy

deploy-backend: check-pushed
	$(LOAD_ENV); bash scripts/deploy_ks001.sh "$(SHA)"

check-pushed:
	@git fetch -q github
	@git branch -r --contains "$(SHA)" | grep -q . || { \
	  echo "commit $(SHA) is not on GitHub; push it first (KS-001 deploys from GitHub)" >&2; exit 1; }

smoke:
	$(LOAD_ENV); bash scripts/smoke.sh
