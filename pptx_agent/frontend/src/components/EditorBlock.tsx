import { useRef, useEffect } from "react";
import type { SlideBlock } from "../events";
import { ChartView } from "./ChartView";
import type { ChartKind, ChartSeries } from "./ChartView";
import { ImageBlockEditor } from "./ImageBlockEditor";

interface Props {
  block: SlideBlock;
  selected: boolean;
  onSelect: () => void;
  onChange: (props: Record<string, unknown>) => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  isFirst: boolean;
  isLast: boolean;
  jobId?: string;
}

export function EditorBlock(props: Props) {
  const { block, selected, onSelect, onChange, onDelete, onMoveUp, onMoveDown, isFirst, isLast, jobId } = props;
  return (
    <div
      className={`editor-block block-${block.type} ${selected ? "selected" : ""}`}
      data-block-id={block.id}
      onClick={onSelect}
      role="group"
      aria-label={`${block.type} block`}
    >
      {selected && (
        <div className="block-toolbar" onClick={(e) => e.stopPropagation()}>
          <button type="button" disabled={isFirst} onClick={onMoveUp} title="Move up">↑</button>
          <button type="button" disabled={isLast} onClick={onMoveDown} title="Move down">↓</button>
          <button type="button" onClick={onDelete} title="Delete block" className="danger">✕</button>
        </div>
      )}
      <BlockContent block={block} onChange={onChange} jobId={jobId} />
    </div>
  );
}

function BlockContent({ block, onChange, jobId }: { block: SlideBlock; onChange: (p: Record<string, unknown>) => void; jobId?: string }) {
  const props = block.props as Record<string, unknown>;
  switch (block.type) {
    case "eyebrow":
      return (
        <EditableText
          tag="p"
          className="eyebrow"
          value={String(props.text ?? "")}
          placeholder="Eyebrow"
          onChange={(text) => onChange({ ...props, text })}
        />
      );
    case "heading":
      return (
        <EditableText
          tag="h2"
          value={String(props.text ?? "")}
          placeholder="Heading"
          onChange={(text) => onChange({ ...props, text })}
        />
      );
    case "subheading":
      return (
        <EditableText
          tag="p"
          className="subtitle"
          value={String(props.text ?? "")}
          placeholder="Subheading"
          onChange={(text) => onChange({ ...props, text })}
        />
      );
    case "paragraph":
      return (
        <EditableText
          tag="p"
          value={String(props.text ?? "")}
          placeholder="Paragraph text"
          onChange={(text) => onChange({ ...props, text })}
        />
      );
    case "bullets": {
      const items = (props.items as string[]) || [];
      return (
        <ul>
          {items.map((item, i) => (
            <li key={i}>
              <EditableText
                tag="span"
                value={item}
                placeholder="bullet…"
                onChange={(text) => {
                  const next = [...items];
                  next[i] = text;
                  onChange({ ...props, items: next.filter((v, idx) => v.trim() || idx < items.length - 1) });
                }}
              />
            </li>
          ))}
          <li>
            <button
              type="button"
              className="ghost small"
              onClick={() => onChange({ ...props, items: [...items, ""] })}
            >
              + bullet
            </button>
          </li>
        </ul>
      );
    }
    case "metric_row": {
      const metrics = (props.metrics as Array<{ label: string; value: string }>) || [];
      return (
        <div className="metric-row">
          {metrics.map((m, i) => (
            <div key={i} className="metric">
              <EditableText
                tag="strong"
                value={m.value}
                placeholder="value"
                onChange={(value) => {
                  const next = [...metrics];
                  next[i] = { ...next[i], value };
                  onChange({ ...props, metrics: next });
                }}
              />
              <EditableText
                tag="span"
                value={m.label}
                placeholder="label"
                onChange={(label) => {
                  const next = [...metrics];
                  next[i] = { ...next[i], label };
                  onChange({ ...props, metrics: next });
                }}
              />
            </div>
          ))}
          <button
            type="button"
            className="ghost small"
            onClick={() => onChange({ ...props, metrics: [...metrics, { label: "", value: "" }] })}
          >
            + metric
          </button>
        </div>
      );
    }
    case "quote":
      return (
        <blockquote>
          <EditableText
            tag="span"
            value={String(props.text ?? "")}
            placeholder="Quote"
            onChange={(text) => onChange({ ...props, text })}
          />
          <cite>
            —{" "}
            <EditableText
              tag="span"
              value={String(props.attribution ?? "")}
              placeholder="Attribution"
              onChange={(attribution) => onChange({ ...props, attribution })}
            />
          </cite>
        </blockquote>
      );
    case "callout":
      return (
        <div className={`callout callout-${String(props.tone || "info")}`}>
          <EditableText
            tag="span"
            value={String(props.text ?? "")}
            placeholder="Callout text"
            onChange={(text) => onChange({ ...props, text })}
          />
        </div>
      );
    case "image": {
      return <ImageBlockEditor props={props} onChange={onChange} jobId={jobId} />;
    }
    case "chart":
      return <ChartBlockEditor props={props} onChange={onChange} />;
    case "diagram":
      return <div className="flow"><b>{String(props.kind || "flow")}</b></div>;
    case "spacer":
      return <div className={`spacer spacer-${String(props.size || "md")}`} />;
    case "table": {
      const headers = (props.headers as string[]) || [];
      const rows = (props.rows as string[][]) || [];
      return (
        <div className="block-table-edit">
          <table className="data-table">
            {headers.length > 0 && (
              <thead>
                <tr>{headers.map((h, i) => <th key={i}>{h}</th>)}</tr>
              </thead>
            )}
            {rows.length > 0 && (
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
                ))}
              </tbody>
            )}
          </table>
          <p className="muted small">Edit table via slide.md or regenerate w/ instructions.</p>
        </div>
      );
    }
    case "hero_stat":
      return (
        <div className="hero-stat">
          <EditableText
            tag="strong"
            className="hero-value"
            value={String(props.value || "")}
            placeholder="42%"
            onChange={(value) => onChange({ ...props, value })}
          />
          <EditableText
            tag="span"
            className="hero-label"
            value={String(props.label || "")}
            placeholder="adoption rate"
            onChange={(label) => onChange({ ...props, label })}
          />
        </div>
      );
    case "highlight":
      return (
        <aside className={`highlight highlight-${String(props.tone || "accent")}`}>
          <EditableText
            tag="strong"
            className="highlight-title"
            value={String(props.title || "")}
            placeholder="KEY INSIGHT"
            onChange={(title) => onChange({ ...props, title })}
          />
          <EditableText
            tag="span"
            className="highlight-text"
            value={String(props.text || "")}
            placeholder="Why this matters"
            onChange={(text) => onChange({ ...props, text })}
          />
        </aside>
      );
    default:
      return <p className="muted">unknown block</p>;
  }
}

function ChartBlockEditor({
  props,
  onChange,
}: {
  props: Record<string, unknown>;
  onChange: (p: Record<string, unknown>) => void;
}) {
  const kind = (String(props.kind || "bar") as ChartKind);
  const title = String(props.title || "");
  const labels = (props.labels as string[]) || [];
  const series = (props.series as ChartSeries[]) || [];
  const labelsCsv = labels.join(", ");

  const onSeriesValues = (idx: number, csv: string) => {
    const next = series.map((s, i) =>
      i === idx
        ? {
            ...s,
            values: csv
              .split(/[,\s]+/)
              .map((s) => s.trim())
              .filter(Boolean)
              .map((n) => Number(n))
              .filter((n) => Number.isFinite(n)),
          }
        : s,
    );
    onChange({ ...props, series: next });
  };

  return (
    <div className="chart-edit">
      <ChartView kind={kind} series={series} labels={labels} title={title} />
      <div className="chart-edit-controls">
        <label>
          <span>Kind</span>
          <select value={kind} onChange={(e) => onChange({ ...props, kind: e.target.value })}>
            <option value="bar">bar</option>
            <option value="line">line</option>
            <option value="area">area</option>
            <option value="pie">pie</option>
          </select>
        </label>
        <label>
          <span>Title</span>
          <input
            type="text"
            value={title}
            onChange={(e) => onChange({ ...props, title: e.target.value })}
            placeholder="Chart title"
          />
        </label>
        <label>
          <span>Labels (csv)</span>
          <input
            type="text"
            value={labelsCsv}
            onChange={(e) =>
              onChange({
                ...props,
                labels: e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
            placeholder="Q1, Q2, Q3, Q4"
          />
        </label>
        <div className="chart-series-list">
          {series.map((s, idx) => (
            <div key={idx} className="chart-series-row">
              <input
                type="text"
                value={s.label}
                onChange={(e) => {
                  const next = series.map((row, i) => (i === idx ? { ...row, label: e.target.value } : row));
                  onChange({ ...props, series: next });
                }}
                placeholder="series label"
              />
              <input
                type="text"
                value={(s.values || []).join(", ")}
                onChange={(e) => onSeriesValues(idx, e.target.value)}
                placeholder="1, 2, 3, 4"
              />
              <button
                type="button"
                className="ghost small"
                onClick={() => onChange({ ...props, series: series.filter((_, i) => i !== idx) })}
              >
                ✕
              </button>
            </div>
          ))}
          <button
            type="button"
            className="ghost small"
            onClick={() => onChange({ ...props, series: [...series, { label: "", values: [] }] })}
          >
            + series
          </button>
        </div>
      </div>
    </div>
  );
}

function EditableText({
  tag,
  value,
  placeholder,
  className,
  onChange,
}: {
  tag: "h2" | "h3" | "p" | "span" | "strong" | "figcaption";
  value: string;
  placeholder?: string;
  className?: string;
  onChange: (text: string) => void;
}) {
  const ref = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (ref.current && ref.current.textContent !== value) {
      ref.current.textContent = value;
    }
  }, [value]);

  const common = {
    ref: (el: HTMLElement | null) => {
      ref.current = el;
    },
    className,
    contentEditable: true,
    suppressContentEditableWarning: true,
    role: "textbox",
    "data-placeholder": placeholder,
    onBlur: (e: React.FocusEvent<HTMLElement>) => onChange(e.currentTarget.textContent || ""),
    onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => {
      if (e.key === "Enter" && tag !== "p") {
        e.preventDefault();
        (e.currentTarget as HTMLElement).blur();
      }
    },
  };

  switch (tag) {
    case "h2": return <h2 {...common} />;
    case "h3": return <h3 {...common} />;
    case "p": return <p {...common} />;
    case "strong": return <strong {...common} />;
    case "figcaption": return <figcaption {...common} />;
    case "span":
    default: return <span {...common} />;
  }
}
