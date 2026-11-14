// @vitest-environment jsdom
// The risk slider's note at the left end of its domain: the curve runs on to the left of the first
// selectable position (frontier.s_safe > 0), and the note says why the slider stops there.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { RiskSlider } from "../src/controls/RiskSlider";

afterEach(cleanup);

const NOTE = "Less risk here would mean a lower return and a worse bad year";
const noop = () => undefined;

function show(sSafe: number, opts: { phone?: boolean; details?: boolean } = {}) {
  return render(
    <RiskSlider
      s={Math.max(sSafe, 5)}
      domain={{ s_safe: sSafe, s_max: 47 }}
      xOf={(s) => 40 + s * 10}
      sOf={(px) => (px - 40) / 10}
      width={520}
      low={-0.09}
      typical={0.03}
      details={opts.details ?? false}
      phone={opts.phone ?? false}
      stem={100}
      onChange={noop}
    />,
  );
}

describe("the note at the left end of the risk slider", () => {
  it("is shown when the domain starts to the right of the curve's first node", () => {
    show(2);
    expect(screen.getByTestId("risk-limit").textContent).toBe(NOTE);
  });
  it("is shown for a domain that starts between nodes too, and on a phone", () => {
    show(0.625);
    expect(screen.getByTestId("risk-limit").textContent).toBe(NOTE);
    cleanup();
    show(2, { phone: true });
    expect(screen.getByTestId("risk-limit").textContent).toBe(NOTE);
    cleanup();
    show(2, { details: true });
    expect(screen.getByTestId("risk-limit").textContent).toBe(NOTE);
  });
  it("is not shown when the domain starts at the curve's first node", () => {
    show(0);
    expect(screen.queryByTestId("risk-limit")).toBeNull();
    expect(screen.queryByText(NOTE)).toBeNull();
  });
  it("describes the slider to a screen reader", () => {
    show(2);
    const slider = screen.getByRole("slider");
    const describedBy = slider.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy ?? "")?.textContent).toBe(NOTE);
  });
  it("leaves the slider undescribed when there is no note", () => {
    show(0);
    expect(screen.getByRole("slider").hasAttribute("aria-describedby")).toBe(false);
  });
});
