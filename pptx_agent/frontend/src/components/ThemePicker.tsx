import { useEffect, useState } from "react";

export interface ThemeOption {
  name: string;
  label: string;
  mode: "light" | "dark" | string;
  accent: string;
  bg: string;
}

interface Props {
  value: string;
  onChange: (name: string) => void;
  disabled?: boolean;
}

export function ThemePicker({ value, onChange, disabled }: Props) {
  const [themes, setThemes] = useState<ThemeOption[]>([]);
  const [defaultName, setDefaultName] = useState<string>("slate");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/themes")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (cancelled) return;
        setThemes(data.themes || []);
        setDefaultName(data.default || "slate");
        if (!value && data.default) onChange(data.default);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = value || defaultName;

  return (
    <div className="theme-picker">
      <label>Theme</label>
      {error && <p className="muted small">Theme list unavailable: {error}</p>}
      <div className="theme-swatch-row" role="radiogroup" aria-label="Theme">
        {themes.map((t) => {
          const selected = t.name === current;
          return (
            <button
              key={t.name}
              type="button"
              role="radio"
              aria-checked={selected}
              className={`theme-swatch ${selected ? "selected" : ""}`}
              disabled={disabled}
              onClick={() => onChange(t.name)}
              title={`${t.label} (${t.mode})`}
            >
              <span
                className="theme-swatch-preview"
                style={{ background: t.bg, borderColor: t.accent }}
              >
                <span style={{ background: t.accent }} />
              </span>
              <span className="theme-swatch-label">{t.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
