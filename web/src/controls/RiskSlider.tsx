import { useCallback, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { plain, technical } from "../copy";
import { signedPct } from "../format";
import { useSlide } from "./useSlide";

type Props = {
  s: number;
  domain: { s_safe: number; s_max: number };
  /** Pixel x (relative to the slider's left edge) of column position `s`: the chart's own risk axis. */
  xOf: (s: number) => number;
  /** Inverse of `xOf`. */
  sOf: (px: number) => number;
  /** Width of the slider in px (the chart's width), and where the plot area starts and ends. */
  width: number;
  low: number;
  typical: number;
  details: boolean;
  phone: boolean;
  /** Height of the dashed stem that links the thumb to the chart's risk axis. */
  stem: number;
  /** A tensor is loading: the slider waits. */
  busy?: boolean;
  onChange: (s: number) => void;
};

/** One thumb on the chart's risk axis; its two readouts always move together (spec 3.2). */
export function RiskSlider({ s, domain, xOf, sOf, width, low, typical, details, phone, stem, busy = false, onChange }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const readoutRef = useRef<HTMLDivElement>(null);
  const [readoutW, setReadoutW] = useState(0);
  const single = !(domain.s_max > domain.s_safe);
  const disabled = single || busy;
  const step = (domain.s_max - domain.s_safe) / 200;
  const clamp = useCallback((v: number) => Math.min(domain.s_max, Math.max(domain.s_safe, v)), [domain.s_max, domain.s_safe]);

  const onPoint = useCallback(
    (clientX: number) => {
      const el = ref.current;
      if (!el) return;
      onChange(clamp(sOf(clientX - el.getBoundingClientRect().left)));
    },
    [clamp, onChange, sOf],
  );
  const slide = useSlide(onPoint, disabled);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    const moves: Record<string, number> = {
      ArrowRight: s + step, ArrowUp: s + step, ArrowLeft: s - step, ArrowDown: s - step,
      PageUp: s + 10 * step, PageDown: s - 10 * step, Home: domain.s_safe, End: domain.s_max,
    };
    if (!(e.key in moves)) return;
    e.preventDefault();
    onChange(clamp(moves[e.key]));
  };

  const bad = signedPct(low);
  const typ = signedPct(typical);
  useLayoutEffect(() => {
    if (readoutRef.current) setReadoutW(readoutRef.current.offsetWidth);
  }, [bad, typ, details, phone]);

  const thumbX = xOf(s);
  const railLeft = xOf(0);
  const domainLeft = xOf(domain.s_safe);
  const domainRight = xOf(domain.s_max);
  const half = readoutW / 2;
  const readoutX = Math.min(Math.max(thumbX, half), Math.max(half, width - half));

  return (
    <div className={details ? "risk has-tech" : "risk"}>
      <div
        ref={ref}
        className="rslider"
        data-testid="risk-slider"
        role="slider"
        tabIndex={disabled ? -1 : 0}
        aria-label={plain.xAxis}
        aria-orientation="horizontal"
        aria-valuemin={Number(domain.s_safe.toFixed(4))}
        aria-valuemax={Number(domain.s_max.toFixed(4))}
        aria-valuenow={Number(s.toFixed(4))}
        aria-valuetext={`${plain.riskBad} ${bad}, ${plain.riskTypical} ${typ}`}
        aria-disabled={disabled || undefined}
        onKeyDown={onKeyDown}
        {...slide}
      >
        <span className="r-rail" style={{ left: railLeft, width: Math.max(0, domainLeft - railLeft) }} />
        <span className="r-domain" style={{ left: domainLeft, width: Math.max(0, domainRight - domainLeft) }} />
        <span className="r-fill" style={{ left: domainLeft, width: Math.max(0, thumbX - domainLeft) }} />
        {!phone && <span className="r-stem" style={{ left: thumbX, height: stem }} />}
        <span className="r-thumb" style={{ left: thumbX }} />
      </div>
      <div ref={readoutRef} className="readout" style={phone ? undefined : { left: readoutX, transform: "translateX(-50%)" }}>
        <span className="readout-cap">{plain.riskSlider}</span>
        <span className="readout-figs">
          <span data-testid="risk-readout-bad">
            {plain.riskBad}
            <b className="num">{bad}</b>
          </span>
          <span className="sep" aria-hidden="true">
            ·
          </span>
          <span data-testid="risk-readout-typical">
            {plain.riskTypical}
            <b className="num">{typ}</b>
          </span>
        </span>
        {details && <span className="readout-tech">{technical.riskSlider}</span>}
      </div>
      {single && <p className="risk-note">{plain.riskDisabled}</p>}
    </div>
  );
}
