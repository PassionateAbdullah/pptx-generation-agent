/**
 * PromptForm — Manus-style chat composer pinned at the bottom.
 *
 * Renders a rounded "pill" card: AGENT MODE chip on top-left, textarea in
 * the middle, slide-count + theme chips on the bottom-left, send arrow on
 * the bottom-right. The composer is the only entry point — there is no
 * separate compact / expanded state.
 */
import { useState } from "react";
import type { FormEvent } from "react";
import { ThemePicker } from "./ThemePicker";

interface Props {
  disabled: boolean;
  // When true, the form is acting as a follow-up chat box (a deck already
  // exists). We clear the prompt textarea after submit and use a leaner
  // placeholder so the user sees the composer accepts feedback messages.
  editMode?: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>, prompt: string, slideCount: number, theme: string) => void;
  theme: string;
  onThemeChange: (name: string) => void;
}

export function PromptForm({ disabled, editMode, onSubmit, theme, onThemeChange }: Props) {
  const [prompt, setPrompt] = useState("Create a 10-slide pitch deck for our AI platform.");
  const [slideCount, setSlideCount] = useState(10);
  const [themesOpen, setThemesOpen] = useState(false);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    onSubmit(event, prompt, slideCount, theme);
    if (editMode) {
      // After follow-up message, clear the box so the next instruction can
      // be typed cleanly. Initial-deck prompts stay so the user can tweak
      // and re-submit.
      setPrompt("");
    }
  };

  return (
    <form
      className="prompt-form composer-pill"
      onSubmit={handleSubmit}
    >
      <div className="composer-toprow">
        <span className="composer-mode-chip">
          {editMode ? "EDIT MODE" : "AGENT MODE"}
        </span>
      </div>

      <textarea
        id="prompt"
        className="composer-textarea"
        rows={2}
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        disabled={disabled}
        placeholder={
          editMode
            ? "Edit a slide ('change the chart to blue', 'add 2024 numbers to slide 3'), or start a fresh deck ('now make a new deck about X')."
            : "Describe the deck — I'll research, plan, and draft each slide."
        }
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            (e.currentTarget.form as HTMLFormElement)?.requestSubmit();
          }
        }}
      />

      <div className="composer-botrow">
        <div className="composer-chips">
          <label className="composer-chip count-chip">
            <span className="composer-chip-label">Slides</span>
            <input
              id="slideCount"
              type="number"
              min={5}
              max={25}
              value={slideCount}
              onChange={(event) =>
                setSlideCount(Math.max(5, Math.min(25, Number(event.target.value) || 10)))
              }
              disabled={disabled}
            />
          </label>
          <button
            type="button"
            className={`composer-chip theme-chip ${themesOpen ? "open" : ""}`}
            onClick={() => setThemesOpen((v) => !v)}
            disabled={disabled}
          >
            <span className="composer-chip-label">Theme</span>
            <span className="theme-chip-value">{theme}</span>
          </button>
        </div>
        <button
          type="submit"
          className="composer-send"
          disabled={disabled || !prompt.trim()}
          aria-label="Generate deck"
          title={disabled ? "Generating…" : "Generate deck (⌘↵)"}
        >
          {disabled ? <span className="composer-spinner" /> : "↑"}
        </button>
      </div>

      {themesOpen && (
        <div className="composer-themes-popover">
          <ThemePicker value={theme} onChange={(t) => { onThemeChange(t); setThemesOpen(false); }} disabled={disabled} />
        </div>
      )}
    </form>
  );
}
