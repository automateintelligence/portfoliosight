import { useCallback, useEffect, useState } from "react";

export const THEMES = ["ks-dark", "light", "hud", "grid"] as const;
export type Theme = (typeof THEMES)[number];
export const DEFAULT_THEME: Theme = "ks-dark";
export const STORAGE_KEY = "ps.theme";

export const isTheme = (v: unknown): v is Theme => typeof v === "string" && (THEMES as readonly string[]).includes(v);

export function readStoredTheme(): Theme | null {
  try {
    const v = globalThis.localStorage?.getItem(STORAGE_KEY);
    return isTheme(v) ? v : null;
  } catch {
    return null;
  }
}

export function storeTheme(theme: Theme): void {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, theme);
  } catch {
    // storage may be unavailable (private mode); the URL still carries the theme
  }
}

/** URL `t=` wins over storage, storage over the default. */
export function resolveTheme(urlTheme: string | null | undefined, stored: string | null | undefined): Theme {
  if (isTheme(urlTheme)) return urlTheme;
  if (isTheme(stored)) return stored;
  return DEFAULT_THEME;
}

export const nextTheme = (theme: Theme): Theme => THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];

export function applyTheme(theme: Theme): void {
  if (typeof document !== "undefined") document.documentElement.setAttribute("data-theme", theme);
}

/** A counter that bumps after the theme attribute is on <html>, so canvas layers re-read tokens. */
export function useThemeEpoch(theme: Theme): number {
  const [epoch, setEpoch] = useState(0);
  useEffect(() => {
    applyTheme(theme);
    setEpoch((n) => n + 1);
  }, [theme]);
  return epoch;
}

export function useMediaQuery(query: string): boolean {
  const get = useCallback(() => (typeof window !== "undefined" && "matchMedia" in window ? window.matchMedia(query).matches : false), [query]);
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    if (typeof window === "undefined" || !("matchMedia" in window)) return;
    const mq = window.matchMedia(query);
    const on = () => setMatches(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return matches;
}
