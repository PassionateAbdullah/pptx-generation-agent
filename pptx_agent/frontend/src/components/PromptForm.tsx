import { useState } from "react";
import type { FormEvent } from "react";
import { ThemePicker } from "./ThemePicker";

interface Props {
  disabled: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>, prompt: string, slideCount: number, theme: string) => void;
  theme: string;
  onThemeChange: (name: string) => void;
}

export function PromptForm({ disabled, onSubmit, theme, onThemeChange }: Props) {
  const [prompt, setPrompt] = useState("Create a 10-slide pitch deck for our AI platform.");
  const [slideCount, setSlideCount] = useState(10);

  return (
    <form
      className="prompt-form"
      onSubmit={(event) => onSubmit(event, prompt, slideCount, theme)}
    >
      <label htmlFor="prompt">Prompt</label>
      <textarea
        id="prompt"
        rows={4}
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        disabled={disabled}
      />
      <div className="field-row">
        <label htmlFor="slideCount">Slides</label>
        <input
          id="slideCount"
          type="number"
          min={5}
          max={25}
          value={slideCount}
          onChange={(event) => setSlideCount(Math.max(5, Math.min(25, Number(event.target.value) || 10)))}
          disabled={disabled}
        />
      </div>
      <ThemePicker value={theme} onChange={onThemeChange} disabled={disabled} />
      <button className="btn primary block" type="submit" disabled={disabled}>
        {disabled ? "Generating…" : "Generate Deck"}
      </button>
    </form>
  );
}
