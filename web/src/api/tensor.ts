// The tensor contract on the reading side (spec 7): a zod mirror of
// portfoliosight/engine/tensor.schema.json, plus the array sizes a JSON Schema cannot express.
// Weights and the shipped frontier curve are not re-checked here: the builder guarantees them
// to the 4.11 tolerances and the page recomputes every statistic from the moments.
import { z } from "zod";

const date = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const text = z.string().min(1);
const vector = z.array(z.number()).min(2);
const matrix = z.array(vector).min(2);
const optional = z.number().nullable();

const stressWindow = z.strictObject({ label: text, start: date, end: date, r: z.array(optional).min(2) });

const schema = z.strictObject({
  schema: z.literal(2),
  engine_version: z.string().regex(/^[0-9]+(\.[0-9]+)*$/),
  generation: z.string().regex(/^\d{4}-\d{2}-\d{2}-[0-9.]+$/),
  built_at: z.string().regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/),
  build_seconds: z.number().min(0),
  asof: date,
  frontier_curve: z.strictObject({ sigma: vector, mu: vector }),
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
          source: z.enum(["seed", "tiingo", "tsp", "seed+tiingo"]),
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
  frontier: z.strictObject({ x: vector, y: vector, w: matrix, s_safe: z.number().min(0) }),
  grid: z.strictObject({
    y: vector,
    z: z.array(z.array(optional).min(2)).min(2),
    w: z.array(z.array(vector.nullable()).min(2)).min(2),
    k_div: z.array(z.int().min(-1)).min(2),
    y_div: vector,
    w_div: matrix,
    y_sug: vector,
  }),
  enb_ref: z.number().min(1),
  stress: z.strictObject({ gfc2008: stressWindow, covid2020: stressWindow, rates2022: stressWindow }),
  notes: z.array(text),
});

export type Tensor = z.infer<typeof schema>;

/** Every array whose length is not n (funds), nx (risk columns) or ny (return floors) as spec 7 lays out. */
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

const tensor = schema.superRefine((value, ctx) => {
  for (const message of sizeErrors(value)) ctx.addIssue({ code: "custom", message });
});

/** Validates a tensor document (spec 7) and returns it typed; throws a `ZodError` on a bad one. */
export function parseTensor(json: unknown): Tensor {
  return tensor.parse(json);
}
