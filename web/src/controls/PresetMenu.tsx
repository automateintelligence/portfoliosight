import { ChevronDown, LayoutList } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { plain } from "../copy";

type Props = {
  presets: { id: string; name: string }[];
  active: string | null;
  compact: boolean;
  onSelect: (id: string) => void;
  onCustom: () => void;
};

/** Ready-made portfolios straight from /api/presets (names verbatim), plus "Custom…". */
export function PresetMenu({ presets, active, compact, onSelect, onCustom }: Props) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const current = presets.find((p) => p.id === active);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const label = current ? current.name : "Custom menu";
  return (
    <div className="preset" ref={root}>
      <button
        type="button"
        className={compact ? "btn btn-icon" : "btn preset-btn"}
        data-testid="preset-menu"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Portfolio: ${label}`}
        onClick={() => setOpen((v) => !v)}
      >
        {compact ? (
          <LayoutList size={18} aria-hidden="true" />
        ) : (
          <>
            <span className="preset-name">{label}</span>
            <ChevronDown className="chev" size={15} aria-hidden="true" />
          </>
        )}
      </button>
      {open && (
        <div className="menu" role="menu" aria-label="Portfolios">
          {presets.map((p) => (
            <button
              key={p.id}
              type="button"
              role="menuitemradio"
              aria-checked={p.id === active}
              className="menu-item"
              onClick={() => {
                setOpen(false);
                onSelect(p.id);
              }}
            >
              {p.name}
            </button>
          ))}
          <div className="menu-sep" role="separator" />
          <button
            type="button"
            role="menuitemradio"
            aria-checked={active === null}
            className="menu-item"
            onClick={() => {
              setOpen(false);
              onCustom();
            }}
          >
            {plain.custom}
          </button>
        </div>
      )}
    </div>
  );
}
