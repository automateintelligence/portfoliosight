# PortfolioSight deployment runbook (KS-001 and Cloudflare)

Spec: `docs/specs/2026-10-13-portfoliosight-demo-design.md` §9.5. Each step below records what
was run, the result with secrets removed, and the date. A step that is not done says so.

Conventions used in every command here:

- Settings and secrets come from the laptop env file: `set -a; . ~/.secrets/portfoliosight.env; set +a`.
- No secret value is written in this file. Where a rule or a command holds the gate secret,
  this file shows `<PS_GATE_SECRET>`.
- The server is named only by the setting `PS_KS001_SSH_HOST`.

## Step 1. R2 bucket

Not done yet.

## Step 2. Seed from the laptop

Not done yet.

## Step 3. Data licensing decision

Owner decision 2026-10-13: Tiingo data under personal use for development and testing; commercial license before public opening (§9.6).

The site stays in private preview (`PS_PRIVATE_PREVIEW="1"`) until the owner buys the
commercial license. The provider tier and limits are still measured and recorded under
"Measured".

## Step 4. KS-001: clone, secrets, deploy, catch-up, first generation

Not done yet.

## Step 5. Tunnel ingress and DNS

Not done yet.

## Step 6. WAF rules and rate-limiting rule

Not done yet.

## Step 7. Worker deploy

Not done yet.

## Step 8. Nightly timer, backup and cron

Not done yet.

## Measured

- Provider tier and limits: not measured in production yet.
- 23-fund build time on KS-001: not measured yet.
- Grid in effect: not measured yet.
- Six-lookback preset build time: not measured yet.
