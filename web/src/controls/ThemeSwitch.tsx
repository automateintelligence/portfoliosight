import { Grid3x3, Moon, Radar, Sun } from "lucide-react";
import { nextTheme, THEMES, type Theme } from "../theme/useTheme";

const LABEL: Record<Theme, string> = { "ks-dark": "Dark", light: "Light", hud: "HUD", grid: "Grid" };
const ICON = { "ks-dark": Moon, light: Sun, hud: Radar, grid: Grid3x3 } as const;

type Props = { theme: Theme; compact: boolean; onChange: (theme: Theme) => void };

/** Four looks: KnowledgeSight dark, Light, HUD, Grid. A segmented control, or one cycling button on a phone. */
export function ThemeSwitch({ theme, compact, onChange }: Props) {
  if (compact) {
    const Icon = ICON[theme];
    return (
      <button
        type="button"
        className="btn btn-icon"
        data-testid="theme-switch"
        aria-label={`Look: ${LABEL[theme]}. Switch to ${LABEL[nextTheme(theme)]}`}
        onClick={() => onChange(nextTheme(theme))}
      >
        <Icon size={18} aria-hidden="true" />
      </button>
    );
  }
  return (
    <div className="seg" data-testid="theme-switch" role="radiogroup" aria-label="Look">
      {THEMES.map((id) => {
        const Icon = ICON[id];
        return (
          <button key={id} type="button" role="radio" className="seg-btn" aria-checked={theme === id} onClick={() => onChange(id)}>
            <Icon size={13} aria-hidden="true" />
            <span>{LABEL[id]}</span>
          </button>
        );
      })}
    </div>
  );
}
