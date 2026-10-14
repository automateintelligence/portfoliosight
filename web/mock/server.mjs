// Local stand-in for /api/* (spec 6), used only by `vite preview` during local Playwright runs
// and local development. It serves the UI fixture for every tensor key and never talks to
// anything outside this process.
//
//   GET  /api/presets, /api/symbols, /api/health, /api/tensors/{G}/{hash}/{lookback}
//   POST /api/tensors            (bodies are recorded)
//   POST /api/share              (always 202; nothing is sent)
//   GET  /__mock/posts           recorded POST /api/tensors bodies
//   POST /__mock/config          {"stale": 3, "unavailable": "10y", "challenge": 1, "build409": 2,
//                                 "noGeneration": true}
//   POST /__mock/reset           clears the switches and the recorded bodies
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PS_MOCK_PORT || 8791);
const LOOKBACKS = ["1y", "2y", "3y", "5y", "10y", "ew"];
const SECOND_NAME = "TSP (G, F, C, S, I) [mock-7f3]";

const fixture = JSON.parse(fs.readFileSync(path.join(here, "..", "fixtures", "guide2017_5y.json"), "utf8"));
const G = fixture.generation;
const H1 = fixture.universe.hash;
const shift = (hash, by) => hash.split("").map((c) => ((parseInt(c, 16) + by) % 16).toString(16)).join("");
const H2 = shift(H1, 1);
const H3 = shift(H1, 2);

function holdings() {
  const file = path.join(here, "..", "..", "data", "holdings", "holdings_guide2017_step2.csv");
  const lines = fs.readFileSync(file, "utf8").split(/\r?\n/).filter((l) => l.trim() !== "").slice(1);
  return lines.map((line) => {
    const cells = line.split(",");
    const qty = Number(cells[cells.length - 2]);
    const price = Number(cells[cells.length - 1]);
    return { id: cells[1].trim().toUpperCase(), amount: qty * price };
  });
}

const names = new Map(fixture.universe.funds.map((f) => [f.id, f.name]));
const guideFunds = holdings().map((h) => ({ id: h.id, name: names.get(h.id) ?? h.id }));
const allocation = Object.fromEntries(holdings().map((h) => [h.id, h.amount]));
const lookbacks = (hash) => Object.fromEntries(LOOKBACKS.map((lb) => [lb, { status: "ready", url: `/api/tensors/${G}/${hash}/${lb}` }]));

const presets = {
  generation: G,
  asof: fixture.asof,
  presets: [
    { id: "guide2017", name: "Example Portfolio", hash: H1, funds: guideFunds, allocation, allocation_unit: "$", lookbacks: lookbacks(H1) },
    { id: "tsp", name: SECOND_NAME, hash: H2, funds: guideFunds, allocation: null, allocation_unit: null, lookbacks: lookbacks(H2) },
  ],
};

const symbols = {
  catalog_at: fixture.built_at,
  tiers_served: [1, 2],
  symbols: [
    ...fixture.universe.funds.map((f) => ({ id: f.id, name: f.name, kind: f.kind ?? "etf", tier: 1, first_date: "2007-06-01" })),
    { id: "TSP-L2050", name: "L 2050", kind: "tsp", tier: 1, first_date: "2011-01-31" },
    { id: "SGOV", name: "iShares 0-3 Month Treasury Bond ETF", kind: "etf", tier: 2, first_date: "2020-05-28" },
    { id: "VTIP", name: "Vanguard Short-Term Inflation-Protected Securities ETF", kind: "etf", tier: 2, first_date: "2012-10-16" },
    { id: "VOO", name: "Vanguard S&P 500 ETF", kind: "etf", tier: 2, first_date: "2010-09-09" },
  ],
};

// A small two-fund tensor (uncorrelated funds, so the torsion matrix is the identity). Both
// funds are missing in the 2008 window, which is what the stress-card sentence needs.
function twoFundTensor(lookback) {
  const NX = 48;
  const NY = 32;
  const mu = [0.045, 0.062];
  const sd = [0.006, 0.031];
  const v0 = sd[0] ** 2;
  const v1 = sd[1] ** 2;
  const wOf = (a) => [1 - a, a];
  const sigmaOf = (a) => Math.sqrt((1 - a) ** 2 * v0 + a * a * v1);
  const muOf = (a) => (1 - a) * mu[0] + a * mu[1];
  const enbAt = (a) => {
    const s2 = sigmaOf(a) ** 2;
    const p = [((1 - a) ** 2 * v0) / s2, (a * a * v1) / s2];
    return Math.exp(-p.reduce((acc, x) => acc + (x > 0 ? x * Math.log(x) : 0), 0));
  };
  const aMin = v0 / (v0 + v1);
  const root = (X) => Math.sqrt(Math.max(0, v0 * v0 - (v0 + v1) * (v0 - X * X)));
  const aHigh = (X) => Math.min(1, (v0 + root(X)) / (v0 + v1));
  const aLow = (X) => Math.max(0, (v0 - root(X)) / (v0 + v1));
  const sMin = sigmaOf(aMin);
  const sMax = sigmaOf(1);
  const x = [];
  const aFront = [];
  for (let j = 0; j < NX; j++) {
    x.push(j === NX - 1 ? sMax : sMin + ((sMax - sMin) * j) / (NX - 1));
    aFront.push(j === NX - 1 ? 1 : j === 0 ? aMin : aHigh(x[j]));
  }
  const yFront = aFront.map(muOf);
  const gridY = Array.from({ length: NY }, (_, k) => (k === NY - 1 ? mu[1] : mu[0] + ((mu[1] - mu[0]) * k) / (NY - 1)));
  const z = [];
  const gw = [];
  const kDiv = [];
  const yDiv = [];
  const wDiv = [];
  let enbRef = 0;
  for (let j = 0; j < NX; j++) {
    const zCol = [];
    const wCol = [];
    let best = { enb: enbAt(aFront[j]), ret: yFront[j], k: -1, w: wOf(aFront[j]) };
    for (let k = 0; k < NY; k++) {
      if (gridY[k] > yFront[j] + 1e-12) {
        zCol.push(null);
        wCol.push(null);
        continue;
      }
      const lo = Math.max((gridY[k] - mu[0]) / (mu[1] - mu[0]), aLow(x[j]));
      const a = Math.min(aFront[j], Math.max(lo, 0.5));
      const cell = { enb: enbAt(a), ret: gridY[k], k, w: wOf(a) };
      zCol.push(cell.enb);
      wCol.push(cell.w);
      if (cell.enb > best.enb + 1e-12 || (Math.abs(cell.enb - best.enb) <= 1e-12 && cell.ret > best.ret)) best = cell;
    }
    z.push(zCol);
    gw.push(wCol);
    kDiv.push(best.k);
    yDiv.push(best.ret);
    wDiv.push(best.w);
    enbRef = Math.max(enbRef, best.enb, enbAt(aFront[j]));
  }
  const curveSigma = [];
  const curveMu = [];
  let sSafe = 0;
  let bestLow = -Infinity;
  for (let i = 0; i <= (NX - 1) * 8; i++) {
    const s = i / 8;
    const j = Math.min(NX - 2, Math.floor(s));
    const lam = s - j;
    const a = (1 - lam) * aFront[j] + lam * aFront[j + 1];
    curveSigma.push(sigmaOf(a));
    curveMu.push(muOf(a));
    const low = muOf(a) / 2 - (1.96 * sigmaOf(a)) / Math.SQRT2;
    if (low >= bestLow) {
      bestLow = low;
      sSafe = s;
    }
  }
  const fund = (id, name, lastClose) => ({ id, name, kind: "etf", source: "tiingo", adjusted_through: fixture.asof, fetched_at: fixture.built_at, last_close: lastClose });
  const win = (id, r) => ({ label: fixture.stress[id].label, start: fixture.stress[id].start, end: fixture.stress[id].end, r });
  return {
    schema: fixture.schema,
    engine_version: fixture.engine_version,
    generation: G,
    built_at: fixture.built_at,
    build_seconds: 0.4,
    asof: fixture.asof,
    frontier_curve: { sigma: curveSigma, mu: curveMu },
    universe: {
      hash: H3,
      name: "Custom menu",
      preset_id: null,
      funds: [fund("SGOV", "iShares 0-3 Month Treasury Bond ETF", 100.42), fund("VTIP", "Vanguard Short-Term Inflation-Protected Securities ETF", 49.87)],
      excluded: [],
    },
    lookback: { ...fixture.lookback, id: lookback },
    rf: fixture.rf,
    mu_s: mu,
    mu_sample: mu,
    sigma: sd,
    cov: [[v0, 0], [0, v1]],
    torsion: [[1, 0], [0, 1]],
    torsion_inv_t: [[1, 0], [0, 1]],
    torsion_lambda: [v0, v1],
    bounds: { requested: [{ min: null, max: null }, { min: null, max: null }], min: [0, 0], max: [1, 1], rule: "max(0.25, 3/N)" },
    frontier: { x, y: yFront, w: aFront.map(wOf), s_safe: sSafe },
    grid: { y: gridY, z, w: gw, k_div: kDiv, y_div: yDiv, w_div: wDiv, y_sug: [...yFront] },
    enb_ref: enbRef,
    stress: { gfc2008: win("gfc2008", [null, null]), covid2020: win("covid2020", [0.004, -0.021]), rates2022: win("rates2022", [0.009, -0.034]) },
    notes: fixture.notes ?? [],
  };
}

// Every window is the same fixture, so a ghost line would hide under the primary one. The drawn
// frontier of the other windows is stretched a little, each differently ("ew" barely, so two
// line ends sit close together); the numbers of the view itself are untouched.
const CURVE_STRETCH = { "1y": [1.08, 1.22], "2y": [1.04, 1.12], "3y": [0.97, 0.9], "10y": [1.12, 0.84], ew: [1.005, 1.03] };

function tensorFor(hash, lookback) {
  if (hash === H3) return twoFundTensor(lookback);
  const copy = structuredClone(fixture);
  copy.lookback = { ...copy.lookback, id: lookback };
  const stretch = CURVE_STRETCH[lookback];
  if (stretch) {
    copy.frontier_curve = { sigma: copy.frontier_curve.sigma.map((v) => v * stretch[0]), mu: copy.frontier_curve.mu.map((v) => v * stretch[1]) };
  }
  if (hash === H2) {
    copy.universe = { ...copy.universe, hash: H2, preset_id: "tsp", name: SECOND_NAME };
  } else if (hash !== H1) {
    copy.universe = { ...copy.universe, hash, preset_id: null, name: "Custom menu" };
  }
  return copy;
}

const DEFAULTS = { stale: 0, unavailable: null, challenge: 0, build409: 0, noGeneration: false };
let config = { ...DEFAULTS };
// As the service does: an unusable window is a failed build that is not retried (409).
const windowUnavailable = (lookback) => ({ status: "failed", error: "window_unavailable", attempts: 1, retry: false, details: { lookback, reason: "not enough shared history", rows: 61 } });
const noGeneration = { error: { code: "no_generation", message: "No generation has been published yet.", details: null } };
let posts = [];

const send = (res, status, body, headers = {}) => {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json", "x-ps-preview": "1", "cache-control": "no-store", ...headers });
  res.end(text);
};

const readBody = (req) =>
  new Promise((resolve) => {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => resolve(raw));
  });

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", `http://127.0.0.1:${PORT}`);
  const where = url.pathname;
  const method = req.method ?? "GET";

  if (where === "/__mock/posts" && method === "GET") return send(res, 200, posts);
  if (where === "/__mock/reset" && method === "POST") {
    config = { ...DEFAULTS };
    posts = [];
    return send(res, 200, { ok: true });
  }
  if (where === "/__mock/config" && method === "POST") {
    config = { ...config, ...JSON.parse((await readBody(req)) || "{}") };
    return send(res, 200, config);
  }
  if (!where.startsWith("/api/")) return send(res, 404, { error: { code: "not_found", message: "not found", details: null } });

  if (config.challenge > 0 && where.startsWith("/api/tensors")) {
    config.challenge -= 1;
    res.writeHead(403, { "content-type": "text/html", "cf-mitigated": "challenge" });
    return res.end("<!doctype html><title>Just a moment...</title>");
  }
  if (config.noGeneration && where === "/api/health") {
    return send(res, 200, { status: "initializing", version: fixture.engine_version, generation: null, asof: null, asof_trading_days_behind: null, queue: { depth: 0, building: false }, nightly: null });
  }
  if (config.noGeneration && (where === "/api/presets" || where === "/api/tensors")) return send(res, 503, noGeneration);
  if (method === "GET" && where === "/api/presets") return send(res, 200, presets, { "x-ps-source": "r2" });
  if (method === "GET" && where === "/api/symbols") return send(res, 200, symbols, { "x-ps-source": "r2" });
  if (method === "GET" && where === "/api/health") {
    return send(res, 200, {
      status: "ok", version: fixture.engine_version, generation: G, asof: fixture.asof,
      asof_trading_days_behind: config.stale, queue: { depth: 0, building: false }, nightly: { status: "ok" },
    });
  }
  const hit = where.match(/^\/api\/tensors\/([^/]+)\/([0-9a-f]{16})\/(1y|2y|3y|5y|10y|ew)$/);
  if (method === "GET" && hit && hit[1] === G && config.unavailable === hit[3] && hit[2] === H3) return send(res, 409, windowUnavailable(hit[3]));
  if (method === "GET" && hit && hit[1] === G) return send(res, 200, tensorFor(hit[2], hit[3]), { "x-ps-source": "r2" });
  if (method === "POST" && where === "/api/tensors") {
    const raw = await readBody(req);
    let body = null;
    try {
      body = JSON.parse(raw);
    } catch {
      return send(res, 422, { error: { code: "invalid_request", message: "body is not JSON", details: null } });
    }
    posts.push(body);
    const ids = Array.isArray(body?.funds) ? body.funds.map((f) => String(f?.id)).sort() : [];
    const lookback = LOOKBACKS.includes(body?.lookback) ? body.lookback : "5y";
    const known = new Set(symbols.symbols.map((s) => s.id).concat(guideFunds.map((f) => f.id)));
    const unknown = ids.filter((id) => !known.has(id));
    if (unknown.length > 0) return send(res, 400, { error: { code: "unknown_symbols", message: "unknown symbols", details: { symbols: unknown } } });
    const hash = ids.join(",") === "SGOV,VTIP" ? H3 : H1;
    if (config.unavailable && lookback === config.unavailable) {
      // first answer is "queued"; the poll (and a repeat POST) reports the failed, unretried build
      return send(res, 202, { status: "queued", generation: G, hash, position: 1, eta_s: 30 });
    }
    if (config.build409 > 0) {
      config.build409 -= 1;
      return send(res, 409, { status: "failed", error: "build_failed", attempts: 1, retry: true, details: null });
    }
    return send(res, 200, { status: "ready", generation: G, hash, url: `/api/tensors/${G}/${hash}/${lookback}` });
  }
  if (method === "POST" && where === "/api/share") return send(res, 202, { ok: true });
  return send(res, 404, { error: { code: hit ? "unknown_tensor" : "not_found", message: "not found", details: null } });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`PortfolioSight API mock on http://127.0.0.1:${PORT}`);
});
