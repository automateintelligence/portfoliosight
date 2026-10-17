// The tensor contract on the reading side (spec 7): a zod mirror of
// portfoliosight/engine/tensor.schema.json, plus the array sizes a JSON Schema cannot express.
// Weights and the shipped frontier curve are not re-checked here: the builder guarantees them
// to the 4.11 tolerances and the page recomputes every statistic from the moments.
// Schema 3 (simulation engines spec 7) adds `engines`, `range_default`, `shape` and the
// per-engine `ranges` blocks; schema 2 documents, which have none of them, are still read, so
// a backend rolled back to engine 0.2.0 never breaks the page. Nothing on the page reads the
// new blocks yet.
import { z } from "zod";

const date = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const text = z.string().min(1);
const vector = z.array(z.number()).min(2);
const matrix = z.array(vector).min(2);
const optional = z.number().nullable();

const stressWindow = z.strictObject({ label: text, start: date, end: date, r: z.array(optional).min(2) });

// A one-year range (spec 4.9): the bootstrap's bad / typical / good year and the normal range.
// `of` is the shape of each number: one per mix (a vector), one per ladder level (a matrix),
// or a single mix (a number).
const range = <T extends z.ZodType>(of: T) =>
  z.strictObject({ bad: of, typical: of, good: of, normal: z.strictObject({ low: of, mid: of, high: of }) });
const unitVector = z.array(z.number().min(0).max(1)).min(2);

// One engine's own figures (schema 3): bad / typical / good only; the normal range is the same
// for every engine and lives in the kept `range` blocks. History replay is always there.
export const ENGINE_IDS = ["replay", "garch", "copula"] as const;
const figures = <T extends z.ZodType>(of: T) => z.strictObject({ bad: of, typical: of, good: of });
const byEngine = <T extends z.ZodType>(block: T) => z.strictObject({ replay: block, garch: block.optional(), copula: block.optional() });
const frontierFigures = z.strictObject({ s_safe: z.number().min(0), bad: vector, typical: vector, good: vector });

const replayMethod = z.strictObject({
  name: text,
  horizon_days: z.int().min(1),
  paths: z.int().min(1),
  mean_block_days: z.int().min(1),
  percentiles: z.array(z.number()).length(3),
  percentile_method: z.literal("linear"),
  seed: z.int(),
});
const garchMethod = z.strictObject({
  name: z.literal("garch_t_fhs"),
  paths: z.int().min(1),
  horizon_days: z.int().min(1),
  seed: z.int(),
  start: z.literal("long_run"),
  shape_rows: z.int().min(1),
  qse: z.string().regex(/^[0-9a-f]{7,40}$/),
  arch: text,
});
// An engine is ready with a method and no reason, or unavailable with a reason and no method.
const status = z.enum(["ready", "unavailable"]);
const statusRule = (e: { status: string; reason: string | null; method: unknown }) =>
  e.status === "ready" ? e.reason === null && e.method !== null : e.reason !== null && e.method === null;
const statusMessage = { message: "a ready engine has a method and no reason; an unavailable one a reason and no method" };
const engines = z.strictObject({
  replay: z.strictObject({ status: z.literal("ready"), reason: z.null(), method: replayMethod }),
  garch: z.strictObject({ status, reason: text.nullable(), method: garchMethod.nullable() }).refine(statusRule, statusMessage),
  // the copula's method fields arrive with the engine
  copula: z.strictObject({ status, reason: text.nullable(), method: z.strictObject({ name: text }).nullable() }).refine(statusRule, statusMessage),
});
const shape = z.strictObject({
  rows: z.int().min(2),
  start: date,
  end: date,
  sample_sha256: z.string().regex(/^[0-9a-f]{64}$/),
  pool_rows: z.int().min(0),
  funds: z
    .array(
      z.strictObject({
        id: text,
        status: z.enum(["garch", "near_constant", "fit_failed", "non_stationary", "insufficient_history"]),
        rows: z.int().min(2),
        mu: z.number(),
        omega: z.number().min(0),
        alpha: z.number().min(0),
        beta: z.number().min(0),
        nu: optional,
        long_run_sigma_annual: z.number().min(0),
        margin: z.enum(["empirical", "zero"]).nullable(),
      }),
    )
    .min(2),
  outliers: z.array(z.strictObject({ id: text, date, z: z.number() })),
  lower_tail_5pct: matrix.nullable(),
  tree_loglik_share: z.array(z.number()).min(1).nullable(),
});

const schema = z.strictObject({
  schema: z.union([z.literal(2), z.literal(3)]),
  engine_version: z.string().regex(/^[0-9]+(\.[0-9]+)*$/),
  generation: z.string().regex(/^\d{4}-\d{2}-\d{2}-[0-9.]+$/),
  built_at: z.string().regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/),
  build_seconds: z.number().min(0),
  asof: date,
  frontier_curve: z.strictObject({ sigma: vector, mu: vector }),
  frontier_uncapped: z.strictObject({ sigma: vector, mu: vector }),
  universe: z.strictObject({
    hash: z.string().regex(/^[0-9a-f]{16}$/),
    name: text,
    preset_id: z.string().nullable(),
    funds: z
      .array(
        z.strictObject({
          id: text,
          name: text,
          kind: z.enum(["etf", "mutual_fund", "stock", "tsp"]),
          source: z.enum(["seed", "tiingo", "tsp", "seed+tiingo", "lake"]),
          adjusted_through: date,
          fetched_at: text,
          last_close: optional,
        }),
      )
      .min(2),
    excluded: z.array(z.strictObject({ id: text, reason: text, last_close: optional })),
  }),
  lookback: z.strictObject({
    id: z.enum(["1y", "2y", "3y", "5y", "10y", "ew"]),
    start: date,
    end: date,
    rows: z.int().min(126),
    t_eff: z.number().gt(0),
    ew_halflife_days: z.int().nullable(),
    sample_sha256: z.string().regex(/^[0-9a-f]{64}$/),
  }),
  rf: z.number(),
  mu_s: vector,
  mu_sample: vector,
  sigma: vector,
  cov: matrix,
  torsion: matrix,
  torsion_inv_t: matrix,
  torsion_lambda: vector,
  bounds: z.strictObject({
    requested: z.array(z.strictObject({ min: optional, max: optional })).min(2),
    min: vector,
    max: vector,
    rule: z.literal("max(0.25, 3/N)"),
  }),
  frontier: z.strictObject({ x: vector, y: vector, w: matrix, s_safe: z.number().min(0), range: range(vector), ranges: byEngine(frontierFigures).optional() }),
  ladder: z.strictObject({
    y: matrix,
    z: matrix,
    w: z.array(matrix).min(2),
    hop: z.array(z.array(z.boolean()).min(1)).min(2),
    collapsed: z.array(z.boolean()).min(2),
    t_balanced: unitVector,
    y_balanced: vector,
    default_point: z.enum(["balanced", "peak"]),
    t_suggested: unitVector,
    y_suggested: vector,
    range: range(matrix),
    ranges: byEngine(figures(matrix)).optional(),
  }),
  grid: z.strictObject({
    y: vector,
    z: z.array(z.array(optional).min(2)).min(2),
    w: z.array(z.array(vector.nullable()).min(2)).min(2),
    k_div: z.array(z.int().min(-1)).min(2),
    y_div: vector,
    w_div: matrix,
    y_sug: vector,
  }),
  entered: z
    .strictObject({ w: vector, set_aside: z.number().min(0).max(1), range: range(z.number()), ranges: byEngine(figures(z.number())).optional() })
    .nullable(),
  range_method: replayMethod,
  engines: engines.optional(),
  range_default: z.enum(ENGINE_IDS).optional(),
  shape: shape.nullable().optional(),
  enb_ref: z.number().min(1),
  stress: z.strictObject({ gfc2008: stressWindow, covid2020: stressWindow, rates2022: stressWindow }),
  notes: z.array(text),
});

export type Tensor = z.infer<typeof schema>;

/** Every array whose length is not n (funds), nx (risk columns), ny (raster rows) or the ladder's levels as spec 7 lays out. */
function sizeErrors(t: Tensor): string[] {
  const n = t.universe.funds.length;
  const nx = t.frontier.x.length;
  const ny = t.grid.y.length;
  const errors: string[] = [];
  const size = (name: string, array: unknown[], want: number) => {
    if (array.length !== want) errors.push(`${name} has ${array.length} entries, expected ${want}`);
  };
  const rows = (name: string, array: unknown[][], count: number, width: number) => {
    size(name, array, count);
    array.forEach((row, i) => size(`${name}[${i}]`, row, width));
  };

  for (const name of ["mu_s", "mu_sample", "sigma", "torsion_lambda"] as const) size(name, t[name], n);
  for (const name of ["cov", "torsion", "torsion_inv_t"] as const) rows(name, t[name], n, n);
  for (const name of ["requested", "min", "max"] as const) size(`bounds.${name}`, t.bounds[name], n);
  for (const name of ["gfc2008", "covid2020", "rates2022"] as const) size(`stress.${name}.r`, t.stress[name].r, n);
  size("frontier.y", t.frontier.y, nx);
  rows("frontier.w", t.frontier.w, nx, n);
  for (const name of ["sigma", "mu"] as const) size(`frontier_curve.${name}`, t.frontier_curve[name], 8 * (nx - 1) + 1);
  for (const name of ["k_div", "y_div", "y_sug"] as const) size(`grid.${name}`, t.grid[name], nx);
  rows("grid.w_div", t.grid.w_div, nx, n);
  rows("grid.z", t.grid.z, nx, ny);
  rows("grid.w", t.grid.w, nx, ny);
  for (const name of ["sigma", "mu"] as const) size(`frontier_uncapped.${name}`, t.frontier_uncapped[name], nx);
  const levels = t.ladder.y[0]?.length ?? 0;
  for (const name of ["y", "z"] as const) rows(`ladder.${name}`, t.ladder[name], nx, levels);
  rows("ladder.hop", t.ladder.hop, nx, levels - 1);
  size("ladder.w", t.ladder.w, nx);
  t.ladder.w.forEach((column, j) => rows(`ladder.w[${j}]`, column, levels, n));
  for (const name of ["collapsed", "t_balanced", "y_balanced", "t_suggested", "y_suggested"] as const) size(`ladder.${name}`, t.ladder[name], nx);
  for (const name of ["bad", "typical", "good"] as const) {
    size(`frontier.range.${name}`, t.frontier.range[name], nx);
    rows(`ladder.range.${name}`, t.ladder.range[name], nx, levels);
  }
  for (const name of ["low", "mid", "high"] as const) {
    size(`frontier.range.normal.${name}`, t.frontier.range.normal[name], nx);
    rows(`ladder.range.normal.${name}`, t.ladder.range.normal[name], nx, levels);
  }
  if (t.entered !== null) size("entered.w", t.entered.w, n);
  if (errors.length > 0) return errors;

  if (t.frontier.s_safe > nx - 1) errors.push(`frontier.s_safe ${t.frontier.s_safe} is beyond the last column`);
  for (let j = 0; j < nx; j++) {
    for (let k = 0; k < ny; k++) {
      const cell = t.grid.w[j][k];
      if (cell !== null) size(`grid.w[${j}][${k}]`, cell, n);
      if ((cell === null) !== (t.grid.z[j][k] === null)) errors.push(`grid.w[${j}][${k}] and grid.z[${j}][${k}] disagree on null`);
    }
    const kDiv = t.grid.k_div[j];
    if (kDiv >= ny || (kDiv >= 0 && t.grid.w[j][kDiv] === null)) errors.push(`grid.k_div[${j}] = ${kDiv} names no computed cell`);
  }
  return errors;
}

/** What schema 3 adds, present exactly in a schema 3 document, consistent and of the right sizes. */
function engineErrors(t: Tensor): string[] {
  const added: [string, unknown][] = [
    ["engines", t.engines],
    ["range_default", t.range_default],
    ["shape", t.shape],
    ["frontier.ranges", t.frontier.ranges],
    ["ladder.ranges", t.ladder.ranges],
  ];
  if (t.entered !== null) added.push(["entered.ranges", t.entered.ranges]);
  if (t.schema === 2) return added.filter(([, value]) => value !== undefined).map(([name]) => `a schema 2 tensor has no ${name}`);
  const missing = added.filter(([, value]) => value === undefined).map(([name]) => `a schema 3 tensor carries ${name}`);
  if (missing.length > 0 || !t.engines || !t.frontier.ranges || !t.ladder.ranges || t.shape === undefined) return missing;

  const errors: string[] = [];
  const n = t.universe.funds.length;
  const nx = t.frontier.x.length;
  const levels = t.ladder.y[0]?.length ?? 0;
  const ready = ENGINE_IDS.filter((id) => t.engines?.[id].status === "ready");
  const carried = (block: Partial<Record<(typeof ENGINE_IDS)[number], unknown>>) => ENGINE_IDS.filter((id) => block[id] !== undefined);
  const blocks: [string, Partial<Record<(typeof ENGINE_IDS)[number], unknown>>][] = [
    ["frontier.ranges", t.frontier.ranges],
    ["ladder.ranges", t.ladder.ranges],
  ];
  if (t.entered?.ranges) blocks.push(["entered.ranges", t.entered.ranges]);
  for (const [name, block] of blocks) {
    if (carried(block).join() !== ready.join()) errors.push(`${name} carries ${carried(block).join(", ")}, the ready engines are ${ready.join(", ")}`);
  }
  if (t.range_default !== undefined && !ready.includes(t.range_default)) errors.push(`range_default ${t.range_default} is not a ready engine`);
  if (t.engines.garch.status === "ready" && t.shape === null) errors.push("a ready volatility model comes with its shape");
  for (const id of ENGINE_IDS) {
    const front = t.frontier.ranges[id];
    const ladder = t.ladder.ranges[id];
    for (const name of ["bad", "typical", "good"] as const) {
      if (front && front[name].length !== nx) errors.push(`frontier.ranges.${id}.${name} has ${front[name].length} entries, expected ${nx}`);
      if (ladder && (ladder[name].length !== nx || ladder[name].some((row) => row.length !== levels))) {
        errors.push(`ladder.ranges.${id}.${name} is not ${nx} columns of ${levels} levels`);
      }
    }
    if (front && front.s_safe > nx - 1) errors.push(`frontier.ranges.${id}.s_safe ${front.s_safe} is beyond the last column`);
  }
  if (t.shape && t.shape.funds.length !== n) errors.push(`shape.funds has ${t.shape.funds.length} entries, expected ${n}`);
  return errors;
}

const tensor = schema.superRefine((value, ctx) => {
  const sizes = sizeErrors(value);
  for (const message of sizes.length > 0 ? sizes : engineErrors(value)) ctx.addIssue({ code: "custom", message });
});

/** Validates a tensor document (spec 7) and returns it typed; throws a `ZodError` on a bad one. */
export function parseTensor(json: unknown): Tensor {
  return tensor.parse(json);
}
