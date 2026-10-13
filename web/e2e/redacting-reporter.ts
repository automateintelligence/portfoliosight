// The reporter of the production smoke runs: a plain list whose every line passes through
// redact(), so a failure message, a call log or a console line can never print the gate secret,
// a keyed preview link or the test recipient (run rule 15). Playwright also writes a page snapshot
// (error-context.md) for a failed test, which can hold what was typed into a field: every text
// file a test leaves in its output directory is rewritten through redact() as well.
import type { FullConfig, FullResult, Reporter, Suite, TestCase, TestError, TestResult } from "@playwright/test/reporter";
import fs from "node:fs";
import path from "node:path";
import { redact } from "./smoke-lib";

const MARK: Record<TestResult["status"], string> = { passed: "ok  ", failed: "FAIL", timedOut: "TIME", skipped: "skip", interrupted: "STOP" };
// eslint-disable-next-line no-control-regex
const ANSI = /\u001b\[[0-9;]*m/g;

export default class RedactingReporter implements Reporter {
  private readonly counts: Record<string, number> = {};
  private readonly notPassed: string[] = [];
  private readonly outputDirs = new Set<string>();

  /** Rewrites the text files under `dir` through redact(); other files are left alone. */
  private scrub(dir: string): void {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) this.scrub(full);
      else if (/\.(md|txt|json|log|html|xml|ya?ml)$/i.test(entry.name)) {
        const text = fs.readFileSync(full, "utf8");
        const clean = redact(text);
        if (clean !== text) fs.writeFileSync(full, clean);
      }
    }
  }

  private line(text: string): void {
    process.stdout.write(`${redact(text.replace(ANSI, ""))}\n`);
  }

  private error(error: TestError): void {
    const where = error.location ? ` (${error.location.file}:${error.location.line})` : "";
    this.line(`      ${(error.message ?? error.value ?? "error").split("\n").join("\n      ")}${where}`);
  }

  printsToStdio(): boolean {
    return true;
  }

  onBegin(config: FullConfig, suite: Suite): void {
    for (const project of config.projects) this.outputDirs.add(project.outputDir);
    this.line(`Running ${suite.allTests().length} tests in ${config.projects.length} projects`);
  }

  onStdOut(chunk: string | Buffer): void {
    this.line(`    | ${String(chunk).trimEnd()}`);
  }

  onStdErr(chunk: string | Buffer): void {
    this.line(`    ! ${String(chunk).trimEnd()}`);
  }

  onError(error: TestError): void {
    this.error(error);
  }

  onTestEnd(test: TestCase, result: TestResult): void {
    const name = `[${test.parent.project()?.name ?? "?"}] ${test.title}`;
    for (const attachment of result.attachments) if (attachment.path) this.scrub(path.dirname(attachment.path));
    this.counts[result.status] = (this.counts[result.status] ?? 0) + 1;
    this.line(`  ${MARK[result.status]}  ${name} (${(result.duration / 1000).toFixed(1)} s)`);
    if (result.status === "passed") return;
    this.notPassed.push(`${MARK[result.status].trim()} ${name}`);
    for (const error of result.errors) this.error(error);
    for (const step of result.steps) if (step.error) this.line(`      at step: ${step.title}`);
  }

  onEnd(result: FullResult): void {
    for (const dir of this.outputDirs) this.scrub(dir);
    const summary = Object.entries(this.counts).map(([status, count]) => `${count} ${status}`).join(", ");
    this.line(`\n${summary || "no tests ran"} (${result.status})`);
    for (const entry of this.notPassed) this.line(`  ${entry}`);
  }
}
