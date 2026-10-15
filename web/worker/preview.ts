// Private-preview gate (spec §9.6). While preview is on, pages and /api/* are served only to a
// request that proves it knows the gate secret: the `x-ps-gate` header, the `ps_preview` cookie,
// or `?k=<secret>` once (which sets the cookie and redirects to the URL without the key).
//
// The secret is never logged, echoed or stored in the cookie. The cookie holds
// hex(HMAC-SHA256(key = secret, message = "ps_preview")). Every comparison hashes both sides
// first, so the constant-time primitive always sees two 32-byte digests and input length
// does not leak.

export interface PreviewEnv {
  PS_GATE_SECRET?: string;
  PS_PRIVATE_PREVIEW?: string;
}

export const PREVIEW_COOKIE = "ps_preview";
const COOKIE_MAX_AGE_S = 30 * 24 * 60 * 60;
const encoder = new TextEncoder();

/** Preview is on unless the var is exactly "0": a missing or mistyped var must not open the site. */
export function isPreviewOn(env: PreviewEnv): boolean {
  return env.PS_PRIVATE_PREVIEW !== "0";
}

/** Constant-time string equality. An unset or empty secret matches nothing. */
export async function secretEquals(candidate: string | null | undefined, secret: string | null | undefined): Promise<boolean> {
  if (candidate === null || candidate === undefined || !secret) return false;
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(candidate)),
    crypto.subtle.digest("SHA-256", encoder.encode(secret)),
  ]);
  return crypto.subtle.timingSafeEqual(a, b);
}

/** hex(HMAC-SHA256(key = secret, message = label)): proves knowledge of the secret without carrying it. */
export async function cookieProof(secret: string, label: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(label)));
  return Array.from(mac, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** The cookie value for a secret: a keyed digest, so the cookie proves knowledge without carrying it. */
export function previewCookieValue(secret: string): Promise<string> {
  return cookieProof(secret, PREVIEW_COOKIE);
}

/** Every value the request's `Cookie` header gives `name` (a browser may send a name twice). */
export function cookieValues(header: string | null, name: string): string[] {
  if (header === null) return [];
  const values: string[] = [];
  for (const part of header.split(";")) {
    const eq = part.indexOf("=");
    if (eq !== -1 && part.slice(0, eq).trim() === name) values.push(part.slice(eq + 1).trim());
  }
  return values;
}

function isParam(part: string, name: string): boolean {
  const eq = part.indexOf("=");
  const rawName = (eq === -1 ? part : part.slice(0, eq)).replaceAll("+", " ");
  try {
    return decodeURIComponent(rawName) === name;
  } catch {
    return false;
  }
}

/** The same URL without the `name` parameter; the rest of the query is kept byte for byte. */
export function withoutParam(url: URL, name: string): string {
  const kept = url.search.slice(1).split("&").filter((part) => part !== "" && !isParam(part, name));
  return url.origin + url.pathname + (kept.length > 0 ? `?${kept.join("&")}` : "");
}

const PREVIEW_PAGE = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>PortfolioSight</title>
<style>
html,body{height:100%;margin:0}
body{display:flex;align-items:center;justify-content:center;background:#141417;color:#e8e8ea;font-family:system-ui,sans-serif}
main{max-width:28rem;padding:2rem;text-align:center}
h1{font-size:1.25rem;font-weight:600;margin:0 0 .75rem}
p{margin:0;color:#a0a0a8;line-height:1.5}
</style>
</head>
<body>
<main>
<h1>PortfolioSight is in private preview</h1>
<p>This site is not open to the public yet.</p>
</main>
</body>
</html>
`;

function previewPage(): Response {
  return new Response(PREVIEW_PAGE, {
    status: 403,
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex" },
  });
}

/**
 * Returns `null` when the request may proceed, otherwise the response to send: the 302 that
 * sets the cookie for a correct `?k=`, or the 403 preview page.
 */
export async function previewGate(request: Request, env: PreviewEnv): Promise<Response | null> {
  if (!isPreviewOn(env)) return null;
  const secret = env.PS_GATE_SECRET;
  const url = new URL(request.url);

  if (await secretEquals(url.searchParams.get("k"), secret)) {
    return new Response(null, {
      status: 302,
      headers: {
        location: withoutParam(url, "k"),
        "set-cookie": `${PREVIEW_COOKIE}=${await previewCookieValue(secret as string)}; HttpOnly; Secure; SameSite=Lax; Max-Age=${COOKIE_MAX_AGE_S}; Path=/`,
        "cache-control": "no-store",
      },
    });
  }
  if (await secretEquals(request.headers.get("x-ps-gate"), secret)) return null;

  const presented = cookieValues(request.headers.get("cookie"), PREVIEW_COOKIE);
  if (secret && presented.length > 0) {
    const expected = await previewCookieValue(secret);
    for (const value of presented) {
      if (await secretEquals(value, expected)) return null;
    }
  }
  return previewPage();
}
