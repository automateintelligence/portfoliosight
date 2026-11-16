// Frontier line labels: every line is named, and names never sit on top of each other.
import { describe, expect, it } from "vitest";
import { placeLabels, type LineEnd } from "../src/chart/Overlay";
import { makeScales } from "../src/chart/scales";
import { lookbackLine, primaryLineName } from "../src/copy";

const scales = (phone: boolean) => makeScales(phone ? 358 : 1040, phone ? 358 : 540, { xMin: 0, xMax: 0.3, yMin: 0, yMax: 0.2 }, phone);
const line = (id: string, sigma: number, mu: number, primary = false): LineEnd => ({ id, label: primary ? primaryLineName(id) : lookbackLine[id], primary, sigma, mu });
const box = (l: ReturnType<typeof placeLabels>[number], charW: number) => {
  const w = l.label.length * charW;
  return { x0: l.anchor === "start" ? l.x : l.x - w, x1: l.anchor === "start" ? l.x + w : l.x, y: l.y };
};
const overlaps = (placed: ReturnType<typeof placeLabels>, charW: number) => {
  const boxes = placed.map((l) => box(l, charW));
  let n = 0;
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) if (Math.abs(boxes[i].y - boxes[j].y) < 12 && boxes[i].x0 < boxes[j].x1 && boxes[j].x0 < boxes[i].x1) n += 1;
  return n;
};

describe("placeLabels", () => {
  it("names the windows as the owner asked", () => {
    expect(lookbackLine["5y"]).toBe("5 years");
    expect(lookbackLine["10y"]).toBe("10 years");
    expect(lookbackLine.ew).toBe("Weighted recent");
  });

  it("names the main line by its window and then the term for the line; ghost lines and the no-limits line keep their names (owner direction 2026-11-15)", () => {
    expect(primaryLineName("10y")).toBe("10 years (Efficient frontier)");
    expect(primaryLineName("5y")).toBe("5 years (Efficient frontier)");
    expect(primaryLineName("ew")).toBe("Weighted recent (Efficient frontier)");
    expect(lookbackLine["10y"]).toBe("10 years");
    expect(lookbackLine.nolimits).toBe("No allocation limits");
  });

  for (const phone of [false, true]) {
    for (const primary of ["1y", "5y", "10y", "ew"]) {
      it(`keeps the longer main-line name inside the chart and clear of the other names, ${primary} as the main line (${phone ? "phone" : "desktop"})`, () => {
        const s = scales(phone);
        const others = ["1y", "3y", "10y", "ew", "nolimits"].filter((id) => id !== primary);
        // the main line ends far right; the ghosts end at the same place, and at spread-out places
        const ends = [line(primary, 0.28, 0.15, true), ...others.map((id, i) => line(id, i % 2 === 0 ? 0.28 : 0.2 + 0.015 * i, i % 2 === 0 ? 0.15 + 0.001 * i : 0.1 + 0.01 * i))];
        const placed = placeLabels(ends, s, phone);
        const charW = phone ? 5.7 : 6.3;
        expect(placed.length).toBe(ends.length);
        expect(overlaps(placed, charW)).toBe(0);
        for (const l of placed) {
          const b = box(l, charW);
          expect(b.x0, `${l.id} starts inside the chart`).toBeGreaterThanOrEqual(0);
          expect(b.x1, `${l.id} ends inside the chart`).toBeLessThanOrEqual(s.width);
          expect(l.y, `${l.id} is below the top`).toBeGreaterThan(0);
          expect(l.y, `${l.id} is above the axis`).toBeLessThan(s.plot.bottom);
        }
        expect(placed.find((l) => l.primary)!.leader, "the main line keeps its place").toBeNull();
      });
    }
  }

  it("labels every line, the primary included, to the right of its end on a desktop", () => {
    const s = scales(false);
    const placed = placeLabels([line("5y", 0.2, 0.12, true), line("10y", 0.17, 0.08)], s, false);
    expect(placed.map((l) => l.id).sort()).toEqual(["10y", "5y"]);
    for (const l of placed) {
      expect(l.anchor).toBe("start");
      expect(l.x).toBeGreaterThan(s.x(l.sigma));
      expect(l.leader).toBeNull();
    }
  });

  for (const phone of [false, true]) {
    it(`steps apart labels whose line ends coincide and joins them with a leader (${phone ? "phone" : "desktop"})`, () => {
      const s = scales(phone);
      const ends = [line("5y", 0.2, 0.12, true), line("ew", 0.2005, 0.1205), line("1y", 0.2, 0.1195), line("2y", 0.201, 0.12), line("3y", 0.2, 0.121), line("10y", 0.1995, 0.12)];
      const placed = placeLabels(ends, s, phone);
      expect(placed.length).toBe(6);
      expect(overlaps(placed, phone ? 5.7 : 6.3)).toBe(0);
      const primary = placed.find((l) => l.primary)!;
      expect(primary.leader, "the primary line keeps its place").toBeNull();
      expect(placed.filter((l) => l.leader !== null).length).toBe(5);
      for (const l of placed) {
        expect(l.y).toBeGreaterThan(0);
        expect(l.y).toBeLessThan(s.height);
      }
    });
  }

  it("puts a label above the end when there is no room to its right", () => {
    const s = scales(false);
    const [l] = placeLabels([line("ew", 0.299, 0.1, true)], s, false);
    expect(l.anchor).toBe("end");
    expect(l.y).toBeLessThan(s.y(0.1));
  });
});
