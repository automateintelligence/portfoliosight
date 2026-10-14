// Pure helpers for the production smoke tests: redaction, the test's own reading of a tensor
// (spec 4.6, 4.9, 4.10, 6), the heat ramp, and the runbook and README rules. Nothing here touches
// a browser or the network, so web/tests/smoke-lib.test.ts can check it under vitest.
import { createHash } from "node:crypto";

// ── Redaction (run rule 15) ──────────────────────────────────────────────────

/** Credentials whose values must never reach test output, plus the one private address. */
export const SECRET_NAMES = [
  "PS_GATE_SECRET",
  "CLOUDFLARE_API_TOKEN",
  "CLOUDFLARE_R2_ACCESS_KEY_ID",
  "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
  "TIINGO_API_KEY",
  "MAILCHANNELS_API_KEY",
  "MAILCHANNELS_DKIM_PRIVATE_KEY",
  "PS_SHARE_TEST_RECIPIENT",
] as const;

export const REDACTED = "[redacted]";

/** `text` with every secret value and every `k=` query value replaced by "[redacted]". */
export function redact(text: string, env: Record<string, string | undefined> = process.env): string {
  let out = text;
  const values = SECRET_NAMES.map((name) => (env[name] ?? "").trim())
    .filter((value) => value.length >= 4)
    .sort((a, b) => b.length - a.length);
  for (const value of values) out = out.split(value).join(REDACTED);
  return out.replace(/([?&]k=)[^&#\s"'<>)]*/g, `$1${REDACTED}`);
}

// ── Universe hash (spec 6, A-PS-29) ──────────────────────────────────────────

export type FundPolicy = { id: string; min?: number | null; max?: number | null };

/** Canonical JSON: keys sorted, no whitespace, `null` for defaults. */
export function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const obj = value as Record<string, unknown>;
  return `{${Object.keys(obj).sort().map((key) => `${JSON.stringify(key)}:${canonical(obj[key])}`).join(",")}}`;
}

/** sha256(canonical({"schema": 2, "funds": [{"id", "min", "max"} sorted by id]})), first 16 hex. */
export function universeHash(funds: FundPolicy[]): string {
  const sorted = funds
    .map((fund) => ({ id: fund.id, min: fund.min ?? null, max: fund.max ?? null }))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return createHash("sha256").update(canonical({ schema: 2, funds: sorted }), "utf8").digest("hex").slice(0, 16);
}

// ── The test's own reading of a tensor ───────────────────────────────────────

export type TensorLike = {
  asof: string;
  generation: string;
  enb_ref: number;
  mu_s: number[];
  cov: number[][];
  torsion_inv_t: number[][];
  torsion_lambda: number[];
  lookback: { id: string };
  universe: { hash: string; funds: { id: string; last_close?: number | null }[]; excluded?: { id: string; reason: string }[] };
  bounds: { requested: { min: number | null; max: number | null }[]; min: number[]; max: number[] };
  frontier: { x: number[]; y: number[]; w: number[][]; s_safe: number };
  frontier_curve: { sigma: number[]; mu: number[] };
  grid: { y: number[]; z: (number | null)[][]; w: (number[] | null)[][]; k_div: number[]; y_div: number[]; w_div: number[][] };
  stress: Record<string, { label: string; r: (number | null)[] }>;
};

const SUBSTEPS = 8;
const RANGE_Z = 1.96;

export const lerp = (arr: number[], pos: number): number => {
  const i = Math.min(Math.max(0, Math.floor(pos)), arr.length - 2);
  const f = pos - i;
  return (1 - f) * arr[i] + f * arr[i + 1];
};

/** Signed percent in a text such as "Bad six months −9.4%" → −9.4 (percentage points). */
export function parsePercent(text: string, what = "text"): number {
  const m = text.replace(/[−–]/g, "-").match(/([+-]?)\s?(\d[\d,]*(?:\.\d+)?)\s*%/);
  if (!m) throw new Error(`${what}: no percent value in "${text}"`);
  return (m[1] === "-" ? -1 : 1) * Number(m[2].replace(/,/g, ""));
}

/** Six-month figures of a mix with yearly (mu, sigma), in percentage points (spec 4.9). */
export function range6mPct(mu: number, sigma: number): { low: number; typical: number; high: number } {
  const spread = (RANGE_Z * sigma) / Math.SQRT2;
  return { low: 100 * (mu / 2 - spread), typical: 100 * (mu / 2), high: 100 * (mu / 2 + spread) };
}

/** The frontier mix at position `s`, read off `frontier_curve` (8 sub-steps per column gap). */
export function frontAt(tensor: TensorLike, s: number) {
  const sigma = lerp(tensor.frontier_curve.sigma, s * SUBSTEPS);
  const mu = lerp(tensor.frontier_curve.mu, s * SUBSTEPS);
  return { sigma, mu, ...range6mPct(mu, sigma) };
}

/** The risk slider's domain: from the tensor's `frontier.s_safe` (the engine's rule, spec 4.9) to the last column. */
export function sliderDomain(tensor: TensorLike): { sSafe: number; sMax: number } {
  return { sSafe: tensor.frontier.s_safe, sMax: tensor.frontier.x.length - 1 };
}

/** Yearly return, yearly risk and ENB (minimum torsion, spec 4.6) of weights `w`. */
export function mixStats(tensor: TensorLike, w: number[]): { mu: number; sigma: number; enb: number } {
  const n = w.length;
  let mu = 0;
  let variance = 0;
  for (let i = 0; i < n; i++) {
    mu += tensor.mu_s[i] * w[i];
    for (let k = 0; k < n; k++) variance += w[i] * tensor.cov[i][k] * w[k];
  }
  let entropy = 0;
  for (let i = 0; i < n; i++) {
    let exposure = 0;
    for (let k = 0; k < n; k++) exposure += tensor.torsion_inv_t[i][k] * w[k];
    const share = (tensor.torsion_lambda[i] * exposure * exposure) / variance;
    if (share > 0) entropy -= share * Math.log(share);
  }
  return { mu, sigma: Math.sqrt(variance), enb: Math.exp(entropy) };
}

/** Good / Average / Fair / Poor for `q = ENB / enb_ref` (spec 4.6). */
export function wordFor(q: number): "Good" | "Average" | "Fair" | "Poor" {
  if (q >= 0.75) return "Good";
  if (q >= 0.5) return "Average";
  if (q >= 0.3) return "Fair";
  return "Poor";
}

/** A mix's return over one stress window (spec 4.10); `value` is null below half coverage. */
export function stressOf(w: number[], r: (number | null)[]): { value: number | null; covered: number; missing: number } {
  let total = 0;
  let held = 0;
  let gained = 0;
  for (let i = 0; i < w.length; i++) {
    total += w[i];
    const ri = r[i];
    if (typeof ri === "number") {
      held += w[i];
      gained += w[i] * ri;
    }
  }
  const covered = total > 0 ? held / total : 0;
  return { value: covered >= 0.5 ? gained / held : null, covered, missing: r.filter((v) => v === null).length };
}

/** Default per-fund ceiling in percent: clamp(3/N, 25%, 100%) (spec 4.4). */
export const ruleMaxPct = (n: number): number => 100 * Math.min(1, Math.max(0.25, 3 / Math.max(1, n)));

/** An integer column inside the slider domain whose ladder has room to walk, nearest the middle. */
export function walkableColumn(tensor: TensorLike): number {
  const { sSafe, sMax } = sliderDomain(tensor);
  const middle = (sSafe + sMax) / 2;
  const spans = tensor.frontier.y.map((y, j) => (tensor.grid.k_div[j] < 0 ? 0 : y - tensor.grid.y_div[j]));
  const widest = Math.max(...spans);
  const usable = spans.map((span, j) => ({ j, span })).filter(({ j, span }) => j >= Math.ceil(sSafe) && j <= sMax && span >= 0.5 * widest && span > 0);
  if (usable.length === 0) throw new Error("no column of this tensor has a diversification ladder inside the risk slider's domain");
  usable.sort((a, b) => Math.abs(a.j - middle) - Math.abs(b.j - middle));
  return usable[0].j;
}

/** A position inside the slider domain where every contributing ladder is collapsed, or null. */
export function collapsedPosition(tensor: TensorLike): number | null {
  const { sSafe, sMax } = sliderDomain(tensor);
  const k = tensor.grid.k_div;
  for (let j = Math.ceil(sSafe); j <= sMax; j++) if (k[j] < 0) return j;
  for (let j = Math.floor(sSafe); j < sMax; j++) {
    if (k[j] < 0 && k[j + 1] < 0) {
      const s = Math.max(j + 0.5, sSafe);
      if (s < j + 1) return s;
    }
  }
  return null;
}

// ── Heat ramp (spec 8) ───────────────────────────────────────────────────────

export type Rgb = [number, number, number];

/** d3-interpolate's interpolateRgbBasis, written out: a uniform cubic B-spline per channel. */
export function rgbBasis(colors: Rgb[]): (t: number) => Rgb {
  const n = colors.length - 1;
  const channel = (c: number) => (tIn: number) => {
    let t = tIn;
    let i: number;
    if (t <= 0) {
      t = 0;
      i = 0;
    } else if (t >= 1) {
      t = 1;
      i = n - 1;
    } else i = Math.floor(t * n);
    const v1 = colors[i][c];
    const v2 = colors[i + 1][c];
    const v0 = i > 0 ? colors[i - 1][c] : 2 * v1 - v2;
    const v3 = i < n - 1 ? colors[i + 2][c] : 2 * v2 - v1;
    const t1 = (t - i / n) * n;
    const t2 = t1 * t1;
    const t3 = t2 * t1;
    return ((1 - 3 * t1 + 3 * t2 - t3) * v0 + (4 - 6 * t2 + 3 * t3) * v1 + (1 + 3 * t1 + 3 * t2 - 3 * t3) * v2 + t3 * v3) / 6;
  };
  const ch = [channel(0), channel(1), channel(2)];
  return (t: number) => [ch[0](t), ch[1](t), ch[2](t)];
}

export const channelDistance = (p: number[], q: number[]): number => Math.max(Math.abs(p[0] - q[0]), Math.abs(p[1] - q[1]), Math.abs(p[2] - q[2]));

export type Cell = { j: number; k: number; q: number; qMin: number; qMax: number };

/**
 * `count` feasible cells spread over Z / enb_ref. A cell qualifies when its 3 × 3 neighbourhood
 * is feasible and it sits two rows under the frontier, so a sample at its centre cannot touch the
 * frontier stroke or an empty cell.
 */
export function pickCells(tensor: TensorLike, count = 20): Cell[] {
  const NX = tensor.frontier.x.length;
  const NY = tensor.grid.y.length;
  const z = tensor.grid.z;
  const cells: Cell[] = [];
  for (let j = 1; j < NX - 1; j++) {
    for (let k = 1; k < NY - 2; k++) {
      if (tensor.grid.y[k + 2] > Math.min(tensor.frontier.y[j - 1], tensor.frontier.y[j])) continue;
      const around: (number | null)[] = [];
      for (let dj = -1; dj <= 1; dj++) for (let dk = -1; dk <= 1; dk++) around.push(z[j + dj][k + dk] ?? null);
      if (around.some((v) => v === null)) continue;
      const values = around as number[];
      cells.push({ j, k, q: (z[j][k] as number) / tensor.enb_ref, qMin: Math.min(...values) / tensor.enb_ref, qMax: Math.max(...values) / tensor.enb_ref });
    }
  }
  if (cells.length < count) throw new Error(`this tensor has only ${cells.length} interior feasible cells; ${count} are needed`);
  cells.sort((a, b) => a.q - b.q);
  return Array.from({ length: count }, (_, i) => cells[Math.round((i * (cells.length - 1)) / (count - 1))]);
}

// ── Runbook and docs rules (DoD 27, 29, 30) ──────────────────────────────────

const SECONDS_RE = /(?<![\w.])(\d+(?:\.\d+)?)\s*(?:seconds|second|secs|sec|s)\b/i;
const GRID_RE = /(?<!\d)(48|32)\s*[x×]\s*(32|24)(?!\d)|NX\s*=\s*(48|32)\b.*?NY\s*=\s*(32|24)\b/i;

/** Every runbook line that carries both a duration in seconds and a grid size, in file order. */
export function benchmarkRecords(runbook: string): { seconds: number; grid: [number, number]; line: string }[] {
  const records = [];
  for (const line of runbook.split(/\r?\n/)) {
    const grid = GRID_RE.exec(line);
    if (!grid) continue;
    const rest = `${line.slice(0, grid.index)} ${line.slice(grid.index + grid[0].length)}`;
    const seconds = SECONDS_RE.exec(rest);
    if (!seconds) continue;
    const nx = Number(grid[1] ?? grid[3]);
    const ny = Number(grid[2] ?? grid[4]);
    records.push({ seconds: Number(seconds[1]), grid: [nx, ny] as [number, number], line: line.trim() });
  }
  return records;
}

const DECISION_RE = /personal use.*?(2026-\d{2}-\d{2})|(2026-\d{2}-\d{2}).*personal use/i;
const STEP3_RE = /\bstep\s*3\b|§\s*9\.5|^\s*(?:#{1,6}\s*)?(?:[-*]\s*)?3[.)]\s/i;

/** Dates of the runbook lines that record the personal-use decision under the step 3 heading. */
export function decisionDates(runbook: string): string[] {
  const found: string[] = [];
  let underStep3 = false;
  for (const line of runbook.split(/\r?\n/)) {
    if (STEP3_RE.test(line)) underStep3 = true;
    const match = DECISION_RE.exec(line);
    if (!match || !underStep3) continue;
    const iso = match[1] ?? match[2];
    const parsed = new Date(`${iso}T00:00:00Z`);
    if (!Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === iso) found.push(iso);
  }
  return found;
}

export const LAKE_PATH = "~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core";
export const BACKUP_PATH = "/mnt/d/portfoliosight-data";

/** What DoD 27 asks of README.md; an empty list means it complies. */
export function readmeProblems(text: string): string[] {
  const problems: string[] = [];
  const lines = text.split(/\r?\n/);
  if (lines[lines.length - 1] === "") lines.pop();
  if (lines.length > 60) problems.push(`README.md has ${lines.length} lines, more than 60`);
  for (const needle of [LAKE_PATH, BACKUP_PATH]) if (!text.includes(needle)) problems.push(`README.md does not contain ${needle}`);
  for (const dir of ["portfoliosight/", "web/", "deploy/", "scripts/", "data/", "docs/"]) if (!text.includes(dir)) problems.push(`README.md does not name ${dir} in its layout`);
  for (const command of ["ruff check", "pyright", "pytest", "npm run lint", "npm run typecheck", "npm test", "scripts/smoke.sh", "scripts/deploy_ks001.sh"]) {
    if (!text.includes(command)) problems.push(`README.md does not give the command ${command}`);
  }
  lines.forEach((line, index) => {
    const around = lines.slice(Math.max(0, index - 1), index + 2).join("\n");
    if (line.includes(LAKE_PATH) && !/\blake\b/i.test(around.split(LAKE_PATH).join(""))) problems.push(`line ${index + 1}: the WSL working copy is not named as the lake`);
    if (line.includes(BACKUP_PATH) && !/\bback(ed)?[ -]?up\b/i.test(around)) problems.push(`line ${index + 1}: ${BACKUP_PATH} is not named as the backup`);
    if (line.split(BACKUP_PATH).join("").includes("/mnt/d")) {
      if (!/mirror/i.test(around)) problems.push(`line ${index + 1}: names /mnt/d other than as QSE's mirror`);
      if (/\/mnt\/d\S*\s+(is|as|holds|hosts)\s+the\s+(data\s*)?lake\b/.test(line)) problems.push(`line ${index + 1}: names /mnt/d as the lake`);
    }
  });
  return problems;
}

/** Appendix B's items plus the tester-login item (run rule 10) that ROADMAP.md must carry. */
export const ROADMAP_ITEMS = ["Paid tier", "Data license", "exact-ENB", "FERS planner", "authorized email domains", "one-time code", "30-day session"];
