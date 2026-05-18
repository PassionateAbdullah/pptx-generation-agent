import { useEffect, useState } from "react";

export interface ThemeTokens {
  ink: string;
  muted: string;
  bg: string;
  panel: string;
  panel_alt: string;
  line: string;
  accent: string;
  accent_strong: string;
  accent_soft: string;
  warn: string;
  danger: string;
  shadow: string;
  radius: string;
  font_display: string;
  font_body: string;
  [key: string]: string;
}

export interface ThemeMeta {
  name: string;
  label: string;
  mode: "light" | "dark" | string;
  accent: string;
  bg: string;
  tokens: ThemeTokens;
}

interface ThemesResponse {
  default: string;
  themes: ThemeMeta[];
}

let cached: Promise<ThemesResponse> | null = null;

function fetchThemes(): Promise<ThemesResponse> {
  if (!cached) {
    cached = fetch("/api/themes")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<ThemesResponse>;
      })
      .catch((err) => {
        cached = null;
        throw err;
      });
  }
  return cached;
}

export function useThemes(): {
  themes: ThemeMeta[];
  defaultName: string;
  byName: (name: string) => ThemeMeta | undefined;
  error: string | null;
} {
  const [themes, setThemes] = useState<ThemeMeta[]>([]);
  const [defaultName, setDefaultName] = useState<string>("slate");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchThemes()
      .then((data) => {
        if (cancelled) return;
        setThemes(data.themes);
        setDefaultName(data.default);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return {
    themes,
    defaultName,
    byName: (name: string) => themes.find((t) => t.name === name),
    error,
  };
}

/**
 * Convert a tokens dict into inline-style CSS-variable mapping suitable for
 * React `style` prop. `font_display` → `--font-display`, etc.
 */
export function tokensToStyle(tokens: ThemeTokens | undefined): React.CSSProperties {
  if (!tokens) return {};
  const style: Record<string, string> = {};
  for (const [key, value] of Object.entries(tokens)) {
    style[`--${key.replace(/_/g, "-")}`] = value;
  }
  return style as React.CSSProperties;
}
