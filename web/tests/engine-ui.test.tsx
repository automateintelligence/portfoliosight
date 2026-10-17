// @vitest-environment jsdom
// The Simulation control, the engine tag and the details lines (engines spec 6): what each
// engine shows, what a tensor that lacks an engine says, and that technical lines stay behind details.
import fs from "node:fs";
import path from "node:path";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseTensor } from "../src/api/client";
import { ResultStrip, type DetailFacts } from "../src/controls/ResultStrip";
import { RiskSlider } from "../src/controls/RiskSlider";
import * as copy from "../src/copy";
import { engineFacts } from "../src/math/engines";
import { stripScale } from "../src/math/stripScale";
import { Settings } from "../src/sections/Settings";
import type { EngineId } from "../src/state/url";

const read = (file: string) => JSON.parse(fs.readFileSync(path.resolve(process.cwd(), file), "utf8"));
const RAW = read("fixtures/guide2017_5y.json");
const OLD = read("tests/tensor-schema2.json");
const noop = () => undefined;

afterEach(cleanup);

const withStatus = (statuses: Record<string, string>) => {
  const raw = structuredClone(RAW);
  for (const fund of raw.shape.funds) if (statuses[fund.id]) fund.status = statuses[fund.id];
  return parseTensor(raw);
};

const facts: DetailFacts = { enb: 3, enbRef: 5, mu: 0.06, sigma: 0.1, lookbackStart: "2020-10-01", lookbackEnd: "2025-10-01", rows: 1250, asof: "2026-10-12", notes: [], defaultPoint: "balanced" };
function strip(tensor: ReturnType<typeof parseTensor>, engine: EngineId, details: boolean) {
  return render(
    <ResultStrip
      low={-0.108}
      typical={0.062}
      high={0.224}
      normal={{ low: -0.1, mid: 0.06, high: 0.22 }}
      scale={stripScale({ min: -0.2, max: 0.35 })}
      value={null}
      word="Good"
      details={details}
      facts={facts}
      engine={engineFacts(tensor, engine)}
      staleAsof={null}
      onToggleDetails={noop}
    />,
  );
}

describe("the engine tag", () => {
  it("names the simulation beside the strip's Selected mix label, muted and small", () => {
    const T = parseTensor(RAW);
    for (const id of ["replay", "garch"] as const) {
      strip(T, id, false);
      const tag = screen.getByTestId("engine-tag");
      expect(tag.textContent).toBe(copy.engineNames[id]);
      expect(tag.closest(".strip-label")?.textContent).toContain("Selected mix");
      cleanup();
    }
    expect(copy.engineNames).toEqual({ replay: "History replay", garch: "Volatility model", copula: "Copula" });
  });

  it("also sits beside the risk slider's readouts", () => {
    const view = (engine: EngineId, details = false) =>
      render(<RiskSlider s={10} domain={{ s_safe: 2, s_max: 47 }} xOf={(s) => s * 10} sOf={(px) => px / 10} width={470} low={-0.05} typical={0.04} details={details} phone={false} stem={60} engine={engine} onChange={noop} />);
    view("garch");
    const tag = screen.getByTestId("engine-tag");
    expect(tag.textContent).toBe("Volatility model");
    expect(tag.closest(".readout")?.textContent).toContain("Best-return mix at this risk");
    expect(screen.getByTestId("risk-readout-bad").textContent).toBe("Bad year−5.0%");
    cleanup();
    view("replay");
    expect(screen.getByTestId("engine-tag").textContent).toBe("History replay");
  });

  it("the slider's technical line follows the engine, behind details only", () => {
    const view = (engine: EngineId, details: boolean) =>
      render(<RiskSlider s={10} domain={{ s_safe: 2, s_max: 47 }} xOf={(s) => s * 10} sOf={(px) => px / 10} width={470} low={-0.05} typical={0.04} details={details} phone={false} stem={60} engine={engine} onChange={noop} />);
    const { container } = view("garch", false);
    expect(container.textContent).not.toContain("GARCH");
    expect(container.textContent).not.toContain("stationary block bootstrap");
    cleanup();
    expect(view("garch", true).container.textContent).toContain(copy.engineRiskSliderTechnical.garch);
    cleanup();
    expect(view("replay", true).container.textContent).toContain(copy.technical.riskSlider);
  });
});

describe("the details' Method line and the lines around it", () => {
  it("History replay: the Method line is today's, and nothing about a fit appears", () => {
    const T = parseTensor(RAW);
    strip(T, "replay", true);
    expect(screen.getByTestId("details-method").textContent).toContain(`Range: ${copy.technical.resultStrip}.`);
    expect(screen.queryByTestId("details-engine")).toBeNull();
    expect(screen.queryByTestId("details-pool")).toBeNull();
    expect(screen.queryByTestId("details-held-constant")).toBeNull();
  });

  it("the volatility model: the plain sentence, the pool size and the technical Method line", () => {
    const T = parseTensor(RAW);
    strip(T, "garch", true);
    expect(screen.getByTestId("details-engine").textContent).toContain(copy.enginePlain.garch);
    expect(screen.getByTestId("details-pool").textContent).toBe(copy.poolLine(RAW.shape.pool_rows));
    const method = screen.getByTestId("details-method").textContent as string;
    expect(method).toContain("GARCH(1,1)-t per fund on up to");
    expect(method).toContain(`${RAW.engines.garch.method.paths.toLocaleString("en-US")} × ${RAW.engines.garch.method.horizon_days}-day paths`);
    expect(method).not.toContain("stationary block bootstrap, mean block 21 days");
    // no fund fell back on the fixture: no such line and no 'constant volatility' in the Method line
    expect(screen.queryByTestId("details-held-constant")).toBeNull();
    expect(method).not.toContain("constant volatility for");
  });

  it("names the funds whose volatility was held constant, with why, only when the tensor names some", () => {
    const first = RAW.shape.funds[0].id;
    const second = RAW.shape.funds[3].id;
    const T = withStatus({ [first]: "near_constant", [second]: "insufficient_history" });
    strip(T, "garch", true);
    const line = screen.getByTestId("details-held-constant");
    expect(line.textContent).toContain(copy.heldConstantLine([first, second]));
    expect(line.textContent).toContain(copy.heldConstantWhy);
    expect(screen.getByTestId("details-method").textContent).toContain(`constant volatility for: ${first}, ${second}`);
    cleanup();
    // under History replay nothing is held constant: the replay uses each fund's own days
    strip(T, "replay", true);
    expect(screen.queryByTestId("details-held-constant")).toBeNull();
    expect(screen.getByTestId("details-method").textContent).not.toContain("constant volatility for");
  });

  it("shows no pool size for a tensor without a shape", () => {
    const raw = structuredClone(RAW);
    raw.shape = null;
    raw.engines.garch = { status: "unavailable", reason: "x", method: null };
    delete raw.frontier.ranges.garch;
    delete raw.ladder.ranges.garch;
    delete raw.entered.ranges.garch;
    const T = parseTensor(raw);
    expect(engineFacts(T, "replay")).toMatchObject({ fallbackFunds: [], poolRows: null });
    strip(T, "replay", true);
    expect(screen.queryByTestId("details-pool")).toBeNull();
  });

  it("with details off, no technical line and no fit appears for any engine", () => {
    const T = withStatus({ [RAW.shape.funds[0].id]: "near_constant" });
    const { container } = strip(T, "garch", false);
    expect(screen.queryByTestId("details-method")).toBeNull();
    expect(container.textContent).not.toMatch(/GARCH|held constant|shocks replayed/);
  });
});

describe("the Simulation control", () => {
  const settings = (tensor: ReturnType<typeof parseTensor>, engine: EngineId, onEngine: (e: EngineId) => void = noop) =>
    render(
      <Settings tensor={tensor} lookback="5y" ghosts={[]} caps={[]} unavailable={{}} details={false} busy={false} problem={null} adminMenuMax={null} engine={engine} onEngine={onEngine} onLookback={noop} onGhost={noop} onCaps={noop} onShare={noop} />,
    );

  it("is a radio group named Simulation, after Years of history, with the three names and descriptions", () => {
    settings(parseTensor(RAW), "replay");
    const group = screen.getByRole("radiogroup", { name: "Simulation" });
    const labels = within(group).getAllByRole("radio");
    expect(labels.map((r) => r.getAttribute("data-testid"))).toEqual(["engine-replay", "engine-garch", "engine-copula"]);
    for (const id of ["replay", "garch", "copula"] as const) {
      const option = screen.getByTestId(`engine-${id}`).closest("label") as HTMLElement;
      expect(option.textContent).toContain(copy.engineNames[id]);
      expect(option.textContent).toContain(copy.engineDescriptions[id]);
    }
    // History replay is the tensor's default and says so; the others do not
    expect(screen.getByTestId("engine-replay").closest("label")?.textContent).toContain("default");
    expect(screen.getByTestId("engine-garch").closest("label")?.textContent).not.toContain("default");
    // order in the section: Years of history, then Simulation
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings.indexOf("Simulation")).toBe(headings.indexOf("Years of history") + 1);
  });

  it("checks the engine on screen and reports a choice", () => {
    const onEngine = vi.fn();
    settings(parseTensor(RAW), "garch", onEngine);
    expect((screen.getByTestId("engine-garch") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId("engine-replay") as HTMLInputElement).checked).toBe(false);
    fireEvent.click(screen.getByTestId("engine-replay"));
    expect(onEngine).toHaveBeenCalledExactlyOnceWith("replay");
  });

  it("disables an engine the tensor does not carry and shows the tensor's reason", () => {
    settings(parseTensor(RAW), "replay");
    const copulaInput = screen.getByTestId("engine-copula") as HTMLInputElement;
    expect(copulaInput.disabled).toBe(true);
    expect(copulaInput.closest("label")?.textContent).toContain(RAW.engines.copula.reason);
    expect((screen.getByTestId("engine-garch") as HTMLInputElement).disabled).toBe(false);
  });

  it("shows the volatility model's own reason when the tensor has no fit", () => {
    const raw = structuredClone(RAW);
    raw.engines.garch = { status: "unavailable", reason: "not enough shared history for the volatility model", method: null };
    delete raw.frontier.ranges.garch;
    delete raw.ladder.ranges.garch;
    delete raw.entered.ranges.garch;
    settings(parseTensor(raw), "replay");
    const garch = screen.getByTestId("engine-garch") as HTMLInputElement;
    expect(garch.disabled).toBe(true);
    expect(garch.closest("label")?.textContent).toContain("not enough shared history for the volatility model");
  });

  it("a schema 2 tensor offers History replay only, the others disabled as not computed for this menu", () => {
    settings(parseTensor(OLD), "replay");
    expect((screen.getByTestId("engine-replay") as HTMLInputElement).disabled).toBe(false);
    for (const id of ["garch", "copula"]) {
      const input = screen.getByTestId(`engine-${id}`) as HTMLInputElement;
      expect(input.disabled).toBe(true);
      expect(input.closest("label")?.textContent).toContain(copy.notComputed);
    }
  });
});
