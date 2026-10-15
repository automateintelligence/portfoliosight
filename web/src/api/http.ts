// Same-origin /api/* calls (spec 6, 9.3). Site-relative URLs only: the page never names another
// origin. Importing this module has no side effects and needs no DOM.
import { z } from "zod";
import { parseTensor, type Tensor } from "./tensor";

/** Thrown when a response carries `cf-mitigated: challenge` (spec 3.2, 9.4). */
export class ChallengeError extends Error {
  constructor() {
    super("challenge");
    this.name = "ChallengeError";
  }
}

/** Thrown when the service has not published its first generation yet (`503 no_generation`). */
export class NoGenerationError extends Error {
  constructor() {
    super("no_generation");
    this.name = "NoGenerationError";
  }
}

const lookbackEntry = z.object({ status: z.string(), url: z.string().optional() }).passthrough();

const presetSchema = z
  .object({
    id: z.string(),
    name: z.string(),
    hash: z.string().optional(),
    funds: z.array(z.object({ id: z.string(), name: z.string().nullish() }).passthrough()),
    allocation: z.record(z.string(), z.number()).nullish(),
    allocation_unit: z.string().nullish(),
    lookbacks: z.record(z.string(), lookbackEntry).default({}),
  })
  .passthrough();

const presetsSchema = z.object({ generation: z.string().nullish(), asof: z.string().nullish(), presets: z.array(presetSchema) }).passthrough();

const symbolsSchema = z
  .object({
    symbols: z.array(z.object({ id: z.string(), name: z.string().nullish(), kind: z.string().nullish(), tier: z.number().nullish(), first_date: z.string().nullish() }).passthrough()),
  })
  .passthrough();

const healthSchema = z.object({ asof: z.string().nullish(), asof_trading_days_behind: z.number().nullish() }).passthrough();

export type Preset = z.infer<typeof presetSchema>;
export type PresetsBody = z.infer<typeof presetsSchema>;
export type SymbolEntry = z.infer<typeof symbolsSchema>["symbols"][number];
export type Health = z.infer<typeof healthSchema>;

const tierSchema = z.object({ tier: z.enum(["public", "admin"]), menu_max: z.number().int().min(2) }).passthrough();

export type Tier = { tier: "public" | "admin"; menuMax: number };
/** The public limit (engines spec 6.2), used until `/api/tier` answers and whenever it cannot. */
export const PUBLIC_TIER: Tier = { tier: "public", menuMax: 30 };

export type TensorAnswer =
  | { kind: "tensor"; tensor: Tensor }
  | { kind: "ready"; url: string }
  | { kind: "pending"; pollUrl: string | null; position: number | null; etaS: number | null }
  | { kind: "failed"; error: string; retry: boolean; details: Record<string, unknown> | null }
  | { kind: "refused"; status: number; code: string; message: string; details: Record<string, unknown> | null };

async function call(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(path, { ...init, headers: { accept: "application/json", ...(init?.headers ?? {}) } });
  if (res.headers.get("cf-mitigated") === "challenge") throw new ChallengeError();
  return res;
}

async function jsonOf(res: Response): Promise<unknown> {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

const asRecord = (v: unknown): Record<string, unknown> => (v !== null && typeof v === "object" ? (v as Record<string, unknown>) : {});

/** `GET /api/presets`; `previewOn` comes from the Worker's `x-ps-preview` header (spec 9.6). */
export async function fetchPresets(): Promise<{ body: PresetsBody; previewOn: boolean }> {
  const res = await call("/api/presets");
  if (res.status === 503) {
    const code = asRecord(asRecord(await jsonOf(res)).error).code;
    if (code === "no_generation") throw new NoGenerationError();
  }
  if (!res.ok) throw new Error(`presets ${res.status}`);
  return { body: presetsSchema.parse(await res.json()), previewOn: res.headers.get("x-ps-preview") === "1" };
}

export async function fetchSymbols(): Promise<SymbolEntry[]> {
  const res = await call("/api/symbols");
  if (!res.ok) throw new Error(`symbols ${res.status}`);
  return symbolsSchema.parse(await res.json()).symbols;
}

/**
 * `GET /api/tier`: this browser's access tier and menu limit, decided by the Worker from the
 * admin cookie. Anything but a clear answer is the public tier; only a challenge throws.
 */
export async function fetchTier(): Promise<Tier> {
  try {
    const res = await call("/api/tier");
    if (!res.ok) return PUBLIC_TIER;
    const body = tierSchema.safeParse(await jsonOf(res));
    return body.success ? { tier: body.data.tier, menuMax: body.data.menu_max } : PUBLIC_TIER;
  } catch (err) {
    if (err instanceof ChallengeError) throw err;
    return PUBLIC_TIER;
  }
}

export async function fetchHealth(): Promise<Health> {
  const res = await call("/api/health");
  if (!res.ok) throw new Error(`health ${res.status}`);
  return healthSchema.parse(await res.json());
}

/** Reads the three answers of spec 6 (200, 202, 409) plus refusals, for both the POST and the GET. */
async function tensorAnswer(res: Response, lookback: string): Promise<TensorAnswer> {
  const body = asRecord(await jsonOf(res));
  if (res.status === 200) {
    if (typeof body.url === "string" && body.status === "ready") return { kind: "ready", url: body.url };
    return { kind: "tensor", tensor: parseTensor(body) };
  }
  if (res.status === 202) {
    const ok = typeof body.generation === "string" && typeof body.hash === "string";
    return {
      kind: "pending",
      pollUrl: ok ? `/api/tensors/${body.generation as string}/${body.hash as string}/${lookback}` : null,
      position: typeof body.position === "number" ? body.position : null,
      etaS: typeof body.eta_s === "number" ? body.eta_s : null,
    };
  }
  if (res.status === 409) {
    const info = body.details !== null && typeof body.details === "object" ? (body.details as Record<string, unknown>) : null;
    return { kind: "failed", error: typeof body.error === "string" ? body.error : "failed", retry: body.retry !== false, details: info };
  }
  const err = asRecord(body.error);
  const details = err.details !== null && typeof err.details === "object" ? (err.details as Record<string, unknown>) : null;
  return {
    kind: "refused",
    status: res.status,
    code: typeof err.code === "string" ? err.code : `http_${res.status}`,
    message: typeof err.message === "string" ? err.message : "",
    details,
  };
}

/** `POST /api/tensors` with the exact JSON string `body` (kept byte-equal across retries). */
export async function postTensor(body: string, lookback: string): Promise<TensorAnswer> {
  const res = await call("/api/tensors", { method: "POST", headers: { "content-type": "application/json" }, body });
  return tensorAnswer(res, lookback);
}

export async function getTensor(url: string, lookback: string): Promise<TensorAnswer> {
  return tensorAnswer(await call(url), lookback);
}

const rangeSchema = z.object({ bad: z.number(), typical: z.number(), good: z.number() }).passthrough();

/** Where a tensor lives: the three parts of its key (spec 6). */
export type TensorKey = { generation: string; hash: string; lookback: string };

/**
 * `POST /api/range` (spec 6): the one-year bad / typical / good year of exact weights on a built
 * tensor. `null` whenever the service cannot answer (409 when the history behind the tensor has
 * changed, any refusal, a challenge, a network failure): the caller then keeps the figures it
 * has. Never throws, so a missing range never interrupts the page.
 */
export async function postRange(key: TensorKey, weights: ArrayLike<number>, signal?: AbortSignal): Promise<{ low: number; typical: number; high: number } | null> {
  try {
    const body = JSON.stringify({ generation: key.generation, hash: key.hash, lookback: key.lookback, weights: Array.from(weights) });
    const res = await call("/api/range", { method: "POST", headers: { "content-type": "application/json" }, body, signal });
    if (res.status !== 200) return null;
    const range = rangeSchema.safeParse(await jsonOf(res));
    return range.success ? { low: range.data.bad, typical: range.data.typical, high: range.data.good } : null;
  } catch {
    return null;
  }
}

export type ShareResult = "sent" | "invalid_recipient" | "invalid_url" | "rate_limited" | "failed";

/** `POST /api/share` (spec 9.3). The Worker re-encodes the URL; nothing but these two fields is sent. */
export async function postShare(to: string, url: string): Promise<ShareResult> {
  let res: Response;
  try {
    res = await call("/api/share", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ to, url }) });
  } catch (err) {
    if (err instanceof ChallengeError) throw err;
    return "failed";
  }
  if (res.status === 202) return "sent";
  if (res.status === 429) return "rate_limited";
  if (res.status === 400) {
    const body = asRecord(await jsonOf(res));
    const code = asRecord(body.error).code ?? body.error ?? body.code;
    return code === "invalid_url" ? "invalid_url" : "invalid_recipient";
  }
  return "failed";
}
