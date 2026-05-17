import { useState } from "react";
import type { FormEvent } from "react";

interface Props {
  disabled: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>, prompt: string, slideCount: number) => void;
}

export function PromptForm({ disabled, onSubmit }: Props) {
  const [prompt, setPrompt] = useState("Create a 10-slide pitch deck for our AI platform.");
  const [slideCount, setSlideCount] = useState(10);

  return (
    <form
      className="prompt-form"
      onSubmit={(event) => onSubmit(event, prompt, slideCount)}
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
      <button className="btn primary block" type="submit" disabled={disabled}>
        {disabled ? "Generating…" : "Generate Deck"}
      </button>
    </form>
  );
}
