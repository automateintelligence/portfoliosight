// Private preview (spec 9.6, A-PS-61): while the site runs on personal-use data, nobody without
// the gate secret gets a page or any data. No test here opens a keyed link, and none tries to
// pass Cloudflare's human check: that leg is the owner's own browser check, H-PS-01.
import fs from "node:fs";
import path from "node:path";
import { WEB, env, expect, redact, run, test } from "./helpers";

const VAR = "PS_PRIVATE_PREVIEW";
const VERSION_ID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/;

/** JSONC to JSON: comments and trailing commas out, strings untouched. */
function stripJsonc(text: string): string {
  let out = "";
  let inString = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (inString) {
      out += char;
      if (char === "\\") out += text[++i] ?? "";
      else if (char === '"') inString = false;
    } else if (char === '"') {
      inString = true;
      out += char;
    } else if (text.startsWith("//", i)) {
      while (i < text.length && text[i] !== "\n") i++;
      out += "\n";
    } else if (text.startsWith("/*", i)) {
      const end = text.indexOf("*/", i + 2);
      i = end < 0 ? text.length : end + 1;
    } else out += char;
  }
  return out.replace(/,(\s*[}\]])/g, "$1");
}

function wrangler(args: string[]) {
  return run(path.join(WEB, "node_modules", ".bin", "wrangler"), args, { cwd: WEB, env: { CI: "1", WRANGLER_SEND_METRICS: "false", NO_COLOR: "1", FORCE_COLOR: "0" }, timeoutMs: 180_000 });
}

test("private preview is on in the committed config and in the deployed Worker", async () => {
  const config = JSON.parse(stripJsonc(fs.readFileSync(path.join(WEB, "wrangler.jsonc"), "utf8"))) as { name: string; vars: Record<string, string> };
  expect(config.name).toBe("portfoliosight");
  expect(config.vars[VAR], `vars.${VAR} in web/wrangler.jsonc`).toBe("1");

  env("CLOUDFLARE_API_TOKEN");
  env("CLOUDFLARE_ACCOUNT_ID");
  const listing = wrangler(["deployments", "list", "--json"]);
  expect(listing.status, `wrangler deployments list: ${listing.stderr.slice(-400)}`).toBe(0);
  const deployments = JSON.parse(listing.stdout) as { created_on: string; versions: { version_id: string; percentage: number }[] }[];
  expect(deployments.length, "deployments of the Worker").toBeGreaterThanOrEqual(1);
  const newest = [...deployments].sort((a, b) => a.created_on.localeCompare(b.created_on)).pop()!;
  const active = [...newest.versions].sort((a, b) => a.percentage - b.percentage).pop()!;
  expect(active.version_id).toMatch(VERSION_ID);
  expect(active.percentage, "the newest deployment serves one version").toBe(100);

  const view = wrangler(["versions", "view", active.version_id, "--json"]);
  expect(view.status, `wrangler versions view: ${view.stderr.slice(-400)}`).toBe(0);
  const bindings: { name?: string; text?: string; value?: string }[] = [];
  const walk = (node: unknown): void => {
    if (Array.isArray(node)) node.forEach(walk);
    else if (node !== null && typeof node === "object") {
      const item = node as { name?: string; text?: string; value?: string };
      if (item.name === VAR) bindings.push(item);
      Object.values(node).forEach(walk);
    }
  };
  walk(JSON.parse(view.stdout));
  expect(bindings.length, `the ${VAR} binding of the active version`).toBe(1);
  expect(String(bindings[0].text ?? bindings[0].value), `the deployed ${VAR}`).toBe("1");
});

test("private preview: without the gate secret no path gives a page or data", async ({ site }) => {
  // Control, and the only use of the secret here: learn a real tensor address to ask for without it.
  const presets = (await site.json("/api/presets")) as { presets: { id: string; lookbacks: Record<string, { url: string }> }[] };
  const tensor = presets.presets.find((preset) => preset.id === "guide2017")!.lookbacks["5y"].url;
  expect(tensor).toMatch(/^\/api\/tensors\/[^/]+\/[0-9a-f]{16}\/5y$/);
  expect((await site.get(tensor)).status(), "with the secret the tensor is there").toBe(200);

  for (const where of ["/", "/api/presets", "/api/symbols", "/api/health", tensor]) {
    const answer = await site.get(where, { gate: false });
    const text = await answer.text();
    const what = redact(`GET ${where} without the secret`);
    expect(answer.status(), what).toBe(403);
    const challenged = answer.headers()["cf-mitigated"] === "challenge";
    expect(challenged || text.includes("private preview"), `${what}: Cloudflare's challenge or the preview page`).toBe(true);
    expect(answer.headers()["x-ps-source"], `${what}: no data source header`).toBeUndefined();
    expect(answer.headers()["set-cookie"] ?? "", `${what}: no preview cookie is handed out`).not.toContain("ps_preview");
    expect(text, `${what}: no page`).not.toContain("chart-canvas");
    let parsed: unknown = null;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
    expect(parsed, `${what}: no JSON body`).toBeNull();
  }

  // A wrong secret is no better than none.
  const wrong = await site.get("/api/presets", { gate: false });
  expect(wrong.status()).toBe(403);
  const refused = await fetch(`${site.origin}/api/presets`, { headers: { "x-ps-gate": "0".repeat(48) }, redirect: "manual" });
  expect(refused.status, "a wrong gate header").toBe(403);
  expect(refused.headers.get("x-ps-source")).toBeNull();
});
