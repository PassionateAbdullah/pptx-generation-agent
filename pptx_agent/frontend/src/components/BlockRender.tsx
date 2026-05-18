/**
 * Read-only block renderer. Mirrors pptx_agent/html_renderer.py dispatch
 * so in-app preview (presentation mode, editor surface, summary thumbnails)
 * looks identical to the exported slides.html.
 */
import type { SlideBlock } from "../events";
import { ChartView } from "./ChartView";

interface Props {
  block: SlideBlock;
}

export function BlockRender({ block }: Props) {
  const props = block.props as Record<string, unknown>;
  const inner = renderBlock(block.type, props);
  return (
    <div className={`block block-${block.type}`} data-block-id={block.id}>
      {inner}
    </div>
  );
}

function renderBlock(type: string, props: Record<string, unknown>): JSX.Element {
  switch (type) {
    case "eyebrow":
      return <p className="eyebrow">{String(props.text ?? "")}</p>;
    case "heading":
      return Number(props.level || 1) <= 1
        ? <h2>{String(props.text ?? "")}</h2>
        : <h3>{String(props.text ?? "")}</h3>;
    case "subheading":
      return <p className="subtitle">{String(props.text ?? "")}</p>;
    case "paragraph":
      return <p>{String(props.text ?? "")}</p>;
    case "bullets": {
      const items = (props.items as string[]) || [];
      return (
        <ul>
          {items.map((item, i) => <li key={i}>{item}</li>)}
        </ul>
      );
    }
    case "metric_row": {
      const metrics = (props.metrics as Array<{ label: string; value: string }>) || [];
      return (
        <div className="metric-row">
          {metrics.map((m, i) => (
            <div className="metric" key={i}>
              <strong>{m.value}</strong>
              <span>{m.label}</span>
            </div>
          ))}
        </div>
      );
    }
    case "quote":
      return (
        <blockquote>
          {String(props.text ?? "")}
          {props.attribution ? <cite>— {String(props.attribution)}</cite> : null}
        </blockquote>
      );
    case "callout":
      return <aside className={`callout callout-${String(props.tone || "info")}`}>{String(props.text ?? "")}</aside>;
    case "image": {
      const src = String(props.src || "");
      const alt = String(props.alt || "");
      const caption = String(props.caption || "");
      return (
        <figure>
          {src
            ? <img src={src} alt={alt} loading="lazy" style={{ objectFit: String(props.fit || "cover") as "cover" | "contain" }} />
            : <div className="image-placeholder">image: {alt || "missing"}</div>}
          {caption ? <figcaption>{caption}</figcaption> : null}
        </figure>
      );
    }
    case "chart": {
      const series = (props.series as Array<{ label: string; values: number[] }>) || [];
      const labels = (props.labels as string[]) || [];
      const title = String(props.title || "");
      const kind = String(props.kind || "bar");
      const legend = series.filter((s) => s.label).map((s, i) => (
        <li key={i}>
          <i className={i % 2 === 0 ? "chart-legend-a" : "chart-legend-b"} />
          {s.label}
        </li>
      ));
      return (
        <div className={`chart chart-${kind}`}>
          <ChartView kind={kind} series={series} labels={labels} title={title} />
          {legend.length > 0 && <ul className="chart-legend">{legend}</ul>}
        </div>
      );
    }
    case "diagram": {
      const kind = String(props.kind || "flow");
      const nodes = (props.nodes as Array<{ label: string }>) || [];
      const labels = nodes.map((n) => n.label).filter(Boolean);
      if (kind === "orbit") {
        return (
          <div className="visual-orbit">
            {Array.from({ length: 5 }).map((_, i) => <span key={i} title={labels[i] || ""} />)}
          </div>
        );
      }
      if (kind === "matrix") {
        const cells = labels.slice(0, 6);
        return <div className="matrix">{cells.map((l, i) => <span key={i}>{l}</span>)}</div>;
      }
      const ls = labels.length ? labels : ["Step 1", "Step 2", "Step 3"];
      return (
        <div className="flow">
          {ls.flatMap((l, i) => (i ? [<i key={`i-${i}`} />, <b key={`b-${i}`}>{l}</b>] : [<b key={`b-${i}`}>{l}</b>]))}
        </div>
      );
    }
    case "spacer":
      return <div className={`spacer spacer-${String(props.size || "md")}`} />;
    case "hero_stat": {
      const value = String(props.value || "");
      const label = String(props.label || "");
      const trend = String(props.trend || "");
      const source = String(props.source_id || "");
      return (
        <div className="hero-stat">
          <div className="hero-value">
            {value}
            {trend && <span className="hero-trend">{trend}</span>}
          </div>
          <div className="hero-label">
            {label}
            {source && <span className="hero-source">[{source}]</span>}
          </div>
        </div>
      );
    }
    case "highlight": {
      const tone = String(props.tone || "accent");
      const title = String(props.title || "");
      const text = String(props.text || "");
      return (
        <aside className={`highlight highlight-${tone}`}>
          {title && <strong className="highlight-title">{title}</strong>}
          <span className="highlight-text">{text}</span>
        </aside>
      );
    }
    default:
      return <span className="muted">[{type}]</span>;
  }
}
