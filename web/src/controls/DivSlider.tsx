import { useCallback, useRef, type KeyboardEvent } from "react";
import { plain, technical } from "../copy";
import { useSlide } from "./useSlide";

type Props = {
  /** Position: 0 = the best-return mix, 1 = the most diversified mix at this risk. It starts at the Optimized mix (the open circle on the chart), so the slider carries no mark of its own. */
  t: number;
  moved: boolean;
  disabled: boolean;
  horizontal: boolean;
  details: boolean;
  onChange: (t: number) => void;
  onReset: () => void;
};

const STEP = 1 / 40;
const PAD = 11; // half the thumb, so the thumb never leaves the track

/** The second slider: moves the point along the column at the risk ceiling (spec 3.2). No numbers. */
export function DivSlider({ t, moved, disabled, horizontal, details, onChange, onReset }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const clamp = (v: number) => Math.min(1, Math.max(0, v));

  const onPoint = useCallback(
    (clientX: number, clientY: number) => {
      const el = ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const frac = horizontal ? (clientX - r.left - PAD) / Math.max(1, r.width - 2 * PAD) : (clientY - r.top - PAD) / Math.max(1, r.height - 2 * PAD);
      onChange(Math.min(1, Math.max(0, frac)));
    },
    [horizontal, onChange],
  );
  const slide = useSlide(onPoint, disabled);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    // Vertical: down is toward "More diversified". Horizontal: right is.
    const toward = horizontal ? ["ArrowRight", "ArrowUp"] : ["ArrowDown", "ArrowLeft"];
    const away = horizontal ? ["ArrowLeft", "ArrowDown"] : ["ArrowUp", "ArrowRight"];
    let next: number | null = null;
    if (toward.includes(e.key)) next = t + STEP;
    else if (away.includes(e.key)) next = t - STEP;
    else if (e.key === "PageDown") next = t + 5 * STEP;
    else if (e.key === "PageUp") next = t - 5 * STEP;
    else if (e.key === "Home") next = horizontal ? 0 : 1;
    else if (e.key === "End") next = horizontal ? 1 : 0;
    if (next === null) return;
    e.preventDefault();
    onChange(clamp(next));
  };

  // The ARIA value rises with the arrow keys that raise it: toward diversified when horizontal,
  // toward return when vertical (where the up arrow moves the thumb up).
  const value = horizontal ? t * 100 : (1 - t) * 100;
  const text = moved ? `${Math.round(t * 100)} of 100 toward ${plain.divMoreDiversified.toLowerCase()}` : plain.optimized;
  const aria = {
    role: "slider" as const,
    tabIndex: disabled ? -1 : 0,
    "aria-label": `${plain.divMoreReturn} or ${plain.divMoreDiversified.toLowerCase()}`,
    "aria-orientation": horizontal ? ("horizontal" as const) : ("vertical" as const),
    "aria-valuemin": 0,
    "aria-valuemax": 100,
    "aria-valuenow": Number(value.toFixed(3)),
    "aria-valuetext": text,
    "aria-disabled": disabled || undefined,
  };
  const pos = (frac: number) => `calc(${PAD}px + (100% - ${2 * PAD}px) * ${frac})`;
  const reset = moved && !disabled && (
    <button type="button" className="btn-link" data-testid="div-reset" onClick={onReset}>
      {plain.resetOptimized}
    </button>
  );
  const note = disabled && <p className="divs-note">{plain.divDisabled}</p>;
  const tech = details && <p className="divs-note">{technical.divSlider}</p>;

  if (horizontal) {
    return (
      <div className="divs divs-h">
        <div className="divs-row">
          <span className="divs-end">{plain.divMoreReturn}</span>
          {reset}
          <span className="divs-end">{plain.divMoreDiversified}</span>
        </div>
        <div ref={ref} className="hslider" data-testid="div-slider" onKeyDown={onKeyDown} {...aria} {...slide}>
          <span className="h-track" />
          <span className="h-thumb" style={{ left: pos(t) }} />
        </div>
        {note}
        {tech}
      </div>
    );
  }
  return (
    <div className="divs">
      <span className="divs-end">{plain.divMoreReturn}</span>
      <div ref={ref} className="vslider" data-testid="div-slider" onKeyDown={onKeyDown} {...aria} {...slide}>
        <span className="v-track" />
        <span className="v-thumb" style={{ top: pos(t) }} />
      </div>
      <span className="divs-end">{plain.divMoreDiversified}</span>
      <div className="divs-reset">
        {reset}
        {note}
        {tech}
      </div>
    </div>
  );
}
