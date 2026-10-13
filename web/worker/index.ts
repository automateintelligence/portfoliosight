// The PortfolioSight Worker (spec §9.3). Every request runs it, in this order:
//
//   1. host: `www` is redirected to the apex, any other host is a 404;
//   2. private preview (spec §9.6): without a credential, a static 403 page and nothing else;
//   3. `/api/*`: reads come straight from R2; `POST /api/tensors`, `GET /api/health` and a
//      tensor that R2 does not hold are forwarded to the origin; `POST /api/share` is handled
//      here; every other `/api/` path or method is a 404;
//   4. everything else is a static asset.
//
// The host check comes first so that a foreign host learns nothing (not even that a preview
// exists) and a preview key is only ever honoured on the apex.
//
// This module must load in plain Node (unit tests): Workers types are ambient only and nothing
// is imported from `cloudflare:*`.

import { isPreviewOn, previewGate } from "./preview";
import { handleShare, jsonError, readBodyLimited, ShareLimiter, type ShareEnv, type ShareLimiterFn } from "./share";

// wrangler binds SHARE_LIMITER to this class by name
export { ShareLimiter };

export interface Env extends ShareEnv {
  API_ORIGIN: string;
  PS_PRIVATE_PREVIEW?: string;
  DATA: R2Bucket;
  ASSETS: Fetcher;
  SHARE_LIMITER: DurableObjectNamespace;
}

const APEX_HOST = "portfoliosight.ai";
const WWW_HOST = "www.portfoliosight.ai";
const CACHE_META = "public, max-age=300";
const CACHE_TENSOR = "public, max-age=86400, immutable";
const CURRENT_TTL_MS = 60_000;
// the origin accepts 16 KB (spec §6); a larger body is refused here rather than buffered
const MAX_FORWARD_BODY_BYTES = 16 * 1024;
const GENERATION = /^\d{4}-\d{2}-\d{2}-[0-9.]+$/;
const TENSOR_HASH = /^[0-9a-f]{16}$/;
const LOOKBACKS: ReadonlySet<string> = new Set(["1y", "2y", "3y", "5y", "10y", "ew"]);
// the only upstream response headers passed on to the visitor
const UPSTREAM_HEADERS = ["content-type", "cache-control", "etag", "retry-after"];

// `meta/current.json` is held per isolate for 60 s (spec §9.3)
let currentGeneration: { generation: string; readAt: number } | null = null;

const unavailable = () => jsonError(503, "unavailable", "The data is not available right now");
const notFound = () => jsonError(404, "not_found", "No such API path");

/** `object` with its body for GET; the result of `head()` (no body) for HEAD. */
function fromR2(object: R2Object | R2ObjectBody, cacheControl: string): Response {
  return new Response("body" in object ? object.body : null, {
    status: 200,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": cacheControl,
      etag: object.httpEtag,
      "x-ps-source": "r2",
    },
  });
}

async function readGeneration(env: Env): Promise<string | null> {
  const now = Date.now();
  if (currentGeneration !== null && now - currentGeneration.readAt < CURRENT_TTL_MS) return currentGeneration.generation;
  currentGeneration = null;
  const object = await env.DATA.get("meta/current.json");
  if (object === null) return null;
  let parsed: unknown;
  try {
    parsed = await object.json();
  } catch {
    return null;
  }
  const generation = typeof parsed === "object" && parsed !== null ? (parsed as { generation?: unknown }).generation : undefined;
  // the value becomes part of an R2 key, so it must have the generation shape
  if (typeof generation !== "string" || !GENERATION.test(generation)) return null;
  currentGeneration = { generation, readAt: now };
  return generation;
}

async function servePresets(env: Env): Promise<Response> {
  const generation = await readGeneration(env);
  if (generation === null) return unavailable();
  const object = await env.DATA.get(`meta/${generation}/presets.json`);
  if (object === null) {
    currentGeneration = null;
    return unavailable();
  }
  return fromR2(object, CACHE_META);
}

async function serveSymbols(env: Env): Promise<Response> {
  const object = await env.DATA.get("meta/symbols.json");
  return object === null ? unavailable() : fromR2(object, CACHE_META);
}

/**
 * Forwards to the origin's `/v1/<rest>` with exactly the headers of spec §9.3. Nothing else of
 * the visitor's request (cookies, query, other headers) goes upstream, and only the body,
 * status and a short list of headers come back.
 */
async function forward(request: Request, env: Env, rest: string, body?: Uint8Array, method = request.method): Promise<Response> {
  if (!env.PS_GATE_SECRET) return unavailable();
  const headers = new Headers({ "x-ps-gate": env.PS_GATE_SECRET, accept: "application/json" });
  const ip = request.headers.get("CF-Connecting-IP");
  if (ip !== null) headers.set("CF-Connecting-IP", ip);
  const contentType = request.headers.get("content-type");
  if (body !== undefined && contentType !== null) headers.set("content-type", contentType);

  let upstream: Response;
  try {
    upstream = await fetch(`${env.API_ORIGIN}/v1/${rest}`, { method, headers, body, redirect: "manual" });
  } catch {
    console.error("origin: unreachable");
    return jsonError(502, "origin_unreachable", "The service is not reachable right now", { "x-ps-source": "origin" });
  }
  const out = new Headers({ "cache-control": "no-store", "x-ps-source": "origin" });
  for (const name of UPSTREAM_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) out.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

async function serveTensor(request: Request, env: Env, segments: string[]): Promise<Response> {
  if (segments.length !== 3) return notFound();
  const [generation, hash, lookback] = segments;
  // checked on the raw path segments, before any R2 read or origin call
  if (!GENERATION.test(generation) || !TENSOR_HASH.test(hash) || !LOOKBACKS.has(lookback)) {
    return jsonError(400, "invalid_request", "Malformed tensor path");
  }
  const rest = `tensors/${generation}/${hash}/${lookback}`;
  if (request.method === "HEAD") {
    // HEAD answers what GET would, without the body: the stored object is not read, and a
    // tensor that is not stored is asked for upstream with GET and only its status passed on
    const stored = await env.DATA.head(`${rest}.json`);
    if (stored !== null) return fromR2(stored, CACHE_TENSOR);
    const answer = await forward(request, env, rest, undefined, "GET");
    await answer.body?.cancel().catch(() => undefined);
    return new Response(null, { status: answer.status, headers: answer.headers });
  }
  const object = await env.DATA.get(`${rest}.json`);
  return object === null ? forward(request, env, rest) : fromR2(object, CACHE_TENSOR);
}

/** Asks the one global limiter object. Any failure to get a clear "allowed" refuses the send. */
function durableLimiter(env: Env): ShareLimiterFn {
  return async (ip, exempt) => {
    try {
      const stub = env.SHARE_LIMITER.get(env.SHARE_LIMITER.idFromName("global"));
      const res = await stub.fetch("https://share-limiter/check", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ip, exempt }),
      });
      if (!res.ok) return false;
      const answer: unknown = await res.json();
      return typeof answer === "object" && answer !== null && (answer as { allowed?: unknown }).allowed === true;
    } catch {
      console.error("share: limiter unavailable");
      return false;
    }
  };
}

async function handleApi(request: Request, env: Env, pathname: string): Promise<Response> {
  const rest = pathname.slice("/api/".length);
  const route = `${request.method} ${rest}`;
  if (route === "GET presets") return servePresets(env);
  if (route === "GET symbols") return serveSymbols(env);
  if (route === "GET health") return forward(request, env, "health");
  if (route === "POST tensors") {
    const body = await readBodyLimited(request, MAX_FORWARD_BODY_BYTES);
    if (body === null) return jsonError(413, "payload_too_large", "The request body is over 16 KB");
    return forward(request, env, "tensors", body);
  }
  if (route === "POST share") return handleShare(request, env, durableLimiter(env));
  if ((request.method === "GET" || request.method === "HEAD") && rest.startsWith("tensors/")) {
    return serveTensor(request, env, rest.split("/").slice(1));
  }
  return notFound();
}

export default {
  async fetch(request: Request, env: Env, _ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.hostname === WWW_HOST) {
      return new Response(null, { status: 301, headers: { location: `https://${APEX_HOST}${url.pathname}${url.search}` } });
    }
    if (url.hostname !== APEX_HOST) return new Response("Not found", { status: 404, headers: { "content-type": "text/plain; charset=utf-8" } });

    const isApi = url.pathname === "/api" || url.pathname.startsWith("/api/");
    let response = await previewGate(request, env);
    if (response === null) {
      if (!isApi) return env.ASSETS.fetch(request);
      try {
        response = await handleApi(request, env, url.pathname);
      } catch {
        // no detail: an error message may quote a URL or a key
        console.error("api: request failed");
        response = unavailable();
      }
    }
    // plan decision: every /api/ response tells the page whether preview is on
    if (isApi) response.headers.set("x-ps-preview", isPreviewOn(env) ? "1" : "0");
    return response;
  },
};
