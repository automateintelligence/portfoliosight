// Access tiers (engines spec 6.2): 30 funds a menu for the public, 100 for an admin. Until
// accounts exist, admin is a browser that knows `PS_ADMIN_SECRET` (its own value, never the
// preview gate's).
//
// Opening any page as `?admin=<secret>` sets the `ps_admin` cookie (HttpOnly, Secure,
// SameSite=Strict, 180 days) and redirects to the same URL without the parameter; `?admin=off`
// clears it. Every `?admin=` request gets the same redirect, so a wrong value is ignored with no
// hint (no oracle), and the value never stays in the address bar or reaches the page. The cookie
// holds hex(HMAC-SHA256(key = secret, message = "ps_admin")), never the secret; rotating the
// secret voids every cookie.
//
// The Worker forwards `x-ps-tier: admin` to the API only when this cookie verifies, and never
// passes on a visitor's own `x-ps-tier` (forward() builds the upstream headers from nothing).

import { cookieProof, cookieValues, secretEquals, withoutParam } from "./preview";

export interface AdminEnv {
  PS_ADMIN_SECRET?: string;
  PS_GATE_SECRET?: string;
  PS_MENU_MAX_PUBLIC?: string;
  PS_MENU_MAX_ADMIN?: string;
}

export type Tier = "public" | "admin";

export const ADMIN_COOKIE = "ps_admin";
export const ADMIN_PARAM = "admin";
export const ADMIN_OFF = "off";
export const TIER_HEADER = "x-ps-tier";
export const DEFAULT_MENU_MAX_PUBLIC = 30;
export const DEFAULT_MENU_MAX_ADMIN = 100;
const ADMIN_MAX_AGE_S = 180 * 24 * 60 * 60;
// a 32-byte secret is 64 hex characters; anything much shorter is a misconfiguration
const MIN_ADMIN_SECRET_LENGTH = 32;
const COOKIE_ATTRIBUTES = "HttpOnly; Secure; SameSite=Strict; Path=/";

/** The admin secret, or `null` (admin off) when it is unset, too short or the gate secret's value. */
function adminSecret(env: AdminEnv): string | null {
  const secret = env.PS_ADMIN_SECRET;
  if (!secret || secret.length < MIN_ADMIN_SECRET_LENGTH) return null;
  if (secret === env.PS_GATE_SECRET) return null;
  return secret;
}

/** True when the request carries a `ps_admin` cookie made from the current admin secret. */
export async function isAdmin(request: Request, env: AdminEnv): Promise<boolean> {
  const secret = adminSecret(env);
  const presented = cookieValues(request.headers.get("cookie"), ADMIN_COOKIE);
  if (secret === null || presented.length === 0) return false;
  const expected = await cookieProof(secret, ADMIN_COOKIE);
  for (const value of presented) {
    if (await secretEquals(value, expected)) return true;
  }
  return false;
}

export async function tierOf(request: Request, env: AdminEnv): Promise<Tier> {
  return (await isAdmin(request, env)) ? "admin" : "public";
}

function limitFrom(value: string | undefined, fallback: number): number {
  return value !== undefined && /^\d{1,4}$/.test(value) && Number(value) >= 2 ? Number(value) : fallback;
}

/** The most funds a menu may hold for `tier`; the vars mirror the API's PS_MENU_MAX_* settings. */
export function menuMax(env: AdminEnv, tier: Tier): number {
  const pub = limitFrom(env.PS_MENU_MAX_PUBLIC, DEFAULT_MENU_MAX_PUBLIC);
  if (tier === "public") return pub;
  return Math.max(pub, limitFrom(env.PS_MENU_MAX_ADMIN, DEFAULT_MENU_MAX_ADMIN));
}

/**
 * The response to a page request carrying `?admin=`, or `null` when it carries none. Always a
 * 302 to the same URL without the parameter: with the cookie for the right secret, with the
 * cookie cleared for `off`, and with nothing else for any other value.
 */
export async function adminLink(request: Request, env: AdminEnv): Promise<Response | null> {
  const url = new URL(request.url);
  if (!url.searchParams.has(ADMIN_PARAM)) return null;
  const presented = url.searchParams.get(ADMIN_PARAM);
  const headers = new Headers({ location: withoutParam(url, ADMIN_PARAM), "cache-control": "no-store", "referrer-policy": "no-referrer" });
  const secret = adminSecret(env);
  if (presented === ADMIN_OFF) {
    headers.set("set-cookie", `${ADMIN_COOKIE}=; ${COOKIE_ATTRIBUTES}; Max-Age=0`);
  } else if (secret !== null && (await secretEquals(presented, secret))) {
    headers.set("set-cookie", `${ADMIN_COOKIE}=${await cookieProof(secret, ADMIN_COOKIE)}; ${COOKIE_ATTRIBUTES}; Max-Age=${ADMIN_MAX_AGE_S}`);
  }
  return new Response(null, { status: 302, headers });
}

/** `GET /api/tier`: what this browser may do, for the page's funds picker and link check. */
export async function serveTier(request: Request, env: AdminEnv): Promise<Response> {
  const tier = await tierOf(request, env);
  return new Response(JSON.stringify({ tier, menu_max: menuMax(env, tier) }), {
    status: 200,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}
