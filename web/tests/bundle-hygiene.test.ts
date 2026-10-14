import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

// The site bundle is public: it must carry no gate header name, no origin host, no mail
// configuration and no third-party font host (spec 9.3, 9.4; DoD 25).
const FORBIDDEN = ["x-ps-gate", "PS_GATE_SECRET", "api.portfoliosight.ai", "MAILCHANNELS", "mailchannels", "fonts.googleapis.com", "fonts.gstatic.com", "ps_preview"];
let out = "";
let files: { name: string; text: string }[] = [];

function walk(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]));
}

beforeAll(() => {
  out = fs.mkdtempSync(path.join(os.tmpdir(), "ps-bundle-"));
  execFileSync(path.resolve("node_modules/.bin/vite"), ["build", "--outDir", out, "--emptyOutDir", "--logLevel", "error"], { cwd: process.cwd(), stdio: "pipe" });
  files = walk(out).map((file) => ({ name: path.relative(out, file), text: fs.readFileSync(file).toString("latin1") }));
}, 120_000);

afterAll(() => {
  if (out) fs.rmSync(out, { recursive: true, force: true });
});

describe("site bundle hygiene", () => {
  it("is the real bundle", () => {
    expect(files.some((f) => f.name.endsWith(".js") && f.text.includes("/api/presets"))).toBe(true);
    expect(files.some((f) => f.name.endsWith(".woff2"))).toBe(true);
  });

  it("holds none of the forbidden strings in any file", () => {
    const hits = files.flatMap((f) => FORBIDDEN.filter((needle) => f.text.includes(needle)).map((needle) => `${f.name}: ${needle}`));
    expect(hits).toEqual([]);
  });

  it("the page and its styles load nothing from another origin", () => {
    const loaders = files.filter((f) => f.name.endsWith(".html") || f.name.endsWith(".css"));
    expect(loaders.length).toBeGreaterThanOrEqual(2);
    for (const f of loaders) expect(/(?:https?:)?\/\/[a-z0-9.-]+\.[a-z]{2,}/i.test(f.text), `${f.name} names an origin`).toBe(false);
  });

  it("loads every font from its own origin", () => {
    const css = files.filter((f) => f.name.endsWith(".css")).map((f) => f.text).join("\n");
    const urls = [...css.matchAll(/url\(([^)]+)\)/g)].map((m) => m[1].replace(/["']/g, ""));
    expect(urls.length).toBeGreaterThanOrEqual(8);
    // Fonts and the HUD theme's decorative dial are the only files a stylesheet loads, both from this origin.
    for (const u of urls) expect(/^"?\/(?:fonts|art)\/[\w.-]+"?$/.test(u), u).toBe(true);
  });
});
