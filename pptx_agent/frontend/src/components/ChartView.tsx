/**
 * Pure-SVG chart renderer mirroring pptx_agent/charts.py.
 *
 * Kept in lockstep with the backend version so the in-app editor preview and
 * the exported slides.html render identically. Uses CSS variables (--accent,
 * --warn, --danger, --muted, --line) so charts inherit deck theme.
 */

export type ChartKind = "bar" | "line" | "area" | "pie";

export interface ChartSeries {
  label: string;
  values: number[];
}

interface Props {
  kind: ChartKind | string;
  series: ChartSeries[];
  labels?: string[];
  title?: string;
}

const VIEW_W = 480;
const VIEW_H = 220;
const PAD_L = 36;
const PAD_R = 12;
const PAD_T = 10;
const PAD_B = 28;
const CHART_W = VIEW_W - PAD_L - PAD_R;
const CHART_H = VIEW_H - PAD_T - PAD_B;

export function ChartView({ kind, series, labels = [], title = "" }: Props) {
  const cleaned = cleanSeries(series);
  const hasData = cleaned.some((s) => s.values.length > 0);
  const normalizedKind = ((kind as string) || "bar").toLowerCase() as ChartKind;

  if (!hasData) {
    return (
      <svg viewBox={`0 0 ${VIEW_W} 80`} className="chart-svg chart-svg-empty" role="img" aria-label={title || "chart"}>
        <rect x={0} y={0} width={VIEW_W} height={80} fill="none" stroke="var(--line, #d9e0e6)" strokeDasharray="4 4" rx={6} />
        <text x={VIEW_W / 2} y={44} textAnchor="middle" style={{ fontFamily: "sans-serif", fontSize: 12, fill: "var(--muted, #53606d)" }}>
          {title || "chart"} — no data
        </text>
      </svg>
    );
  }

  return (
    <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className="chart-svg" role="img" aria-label={title || "chart"}>
      <defs>
        <style>{`
          .csvg-axis { stroke: var(--line, #d9e0e6); stroke-width: 1; }
          .csvg-tick { fill: var(--muted, #53606d); font-size: 9px; }
          .csvg-title { fill: var(--muted, #53606d); font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700; }
          .csvg-bar { fill: var(--accent, #087c7c); }
          .csvg-bar-alt { fill: var(--warn, #d98f1f); }
          .csvg-line { fill: none; stroke: var(--accent, #087c7c); stroke-width: 2; stroke-linejoin: round; }
          .csvg-line-alt { fill: none; stroke: var(--warn, #d98f1f); stroke-width: 2; stroke-linejoin: round; }
          .csvg-area { fill: var(--accent-soft, rgba(0,0,0,0.08)); }
          .csvg-pie-a { fill: var(--accent, #087c7c); }
          .csvg-pie-b { fill: var(--warn, #d98f1f); }
          .csvg-pie-c { fill: var(--danger, #c95746); }
          .csvg-pie-d { fill: var(--muted, #53606d); }
        `}</style>
      </defs>
      {title && (
        <text x={PAD_L} y={PAD_T + 2} className="csvg-title">{title}</text>
      )}
      {normalizedKind === "pie"
        ? renderPie(cleaned[0])
        : normalizedKind === "line" || normalizedKind === "area"
        ? renderLine(cleaned, labels, normalizedKind === "area")
        : renderBar(cleaned, labels)}
    </svg>
  );
}

function cleanSeries(series: ChartSeries[] | undefined): ChartSeries[] {
  if (!series) return [];
  return series.map((s) => ({
    label: String(s.label || ""),
    values: (s.values || []).map((v) => Number(v)).filter((v) => Number.isFinite(v)),
  }));
}

function peakOf(series: ChartSeries[]): number {
  let max = 0;
  for (const s of series) {
    for (const v of s.values) {
      const abs = Math.abs(v);
      if (abs > max) max = abs;
    }
  }
  return max || 1;
}

function renderBar(series: ChartSeries[], labels: string[]) {
  const points = Math.max(...series.map((s) => s.values.length), 0);
  if (!points) return null;
  const peak = peakOf(series);
  const groupW = CHART_W / points;
  const bandW = groupW * 0.78;
  const barW = bandW / Math.max(1, series.length);
  const axisY = PAD_T + CHART_H;
  const nodes: React.ReactNode[] = [
    <line key="axis" className="csvg-axis" x1={PAD_L} y1={axisY} x2={PAD_L + CHART_W} y2={axisY} />,
  ];
  for (let i = 0; i < points; i++) {
    const xCenter = PAD_L + groupW * (i + 0.5);
    series.forEach((s, sIdx) => {
      const v = s.values[i];
      if (v === undefined) return;
      const height = Math.max(2, (Math.abs(v) / peak) * (CHART_H - 8));
      const x = xCenter - bandW / 2 + sIdx * barW;
      const y = axisY - height;
      nodes.push(
        <rect
          key={`b-${i}-${sIdx}`}
          className={sIdx % 2 === 0 ? "csvg-bar" : "csvg-bar-alt"}
          x={x}
          y={y}
          width={Math.max(2, barW - 2)}
          height={height}
          rx={2}
        />,
      );
    });
    const label = labels[i];
    if (label) {
      nodes.push(
        <text key={`l-${i}`} className="csvg-tick" x={xCenter} y={axisY + 14} textAnchor="middle">
          {label}
        </text>,
      );
    }
  }
  return <g>{nodes}</g>;
}

function renderLine(series: ChartSeries[], labels: string[], fill: boolean) {
  const points = Math.max(...series.map((s) => s.values.length), 0);
  if (points < 2) return renderBar(series, labels);
  const peak = peakOf(series);
  const step = CHART_W / (points - 1);
  const axisY = PAD_T + CHART_H;
  const nodes: React.ReactNode[] = [
    <line key="axis" className="csvg-axis" x1={PAD_L} y1={axisY} x2={PAD_L + CHART_W} y2={axisY} />,
  ];
  series.forEach((s, sIdx) => {
    const pts: string[] = [];
    s.values.forEach((v, i) => {
      const x = PAD_L + step * i;
      const y = axisY - Math.max(2, (Math.abs(v) / peak) * (CHART_H - 8));
      pts.push(`${x},${y}`);
    });
    if (!pts.length) return;
    if (fill && sIdx === 0) {
      const areaPts = [...pts, `${PAD_L + step * (s.values.length - 1)},${axisY}`, `${PAD_L},${axisY}`];
      nodes.push(<polygon key={`a-${sIdx}`} className="csvg-area" points={areaPts.join(" ")} />);
    }
    nodes.push(
      <polyline
        key={`p-${sIdx}`}
        className={sIdx % 2 === 0 ? "csvg-line" : "csvg-line-alt"}
        points={pts.join(" ")}
      />,
    );
  });
  for (let i = 0; i < points; i++) {
    const x = PAD_L + step * i;
    const label = labels[i];
    if (label) {
      nodes.push(
        <text key={`lbl-${i}`} className="csvg-tick" x={x} y={axisY + 14} textAnchor="middle">
          {label}
        </text>,
      );
    }
  }
  return <g>{nodes}</g>;
}

function renderPie(series: ChartSeries | undefined) {
  if (!series) return null;
  const values = series.values.map((v) => Math.abs(v)).filter((v) => v > 0);
  if (!values.length) return null;
  const total = values.reduce((a, b) => a + b, 0) || 1;
  const cx = PAD_L + CHART_W / 2;
  const cy = PAD_T + CHART_H / 2;
  const radius = Math.min(CHART_W, CHART_H) / 2 - 6;
  let angle = -Math.PI / 2;
  const palette = ["csvg-pie-a", "csvg-pie-b", "csvg-pie-c", "csvg-pie-d"];
  const nodes: React.ReactNode[] = [];
  values.forEach((value, i) => {
    const sliceAngle = (value / total) * 2 * Math.PI;
    const end = angle + sliceAngle;
    const large = sliceAngle > Math.PI ? 1 : 0;
    const x1 = cx + radius * Math.cos(angle);
    const y1 = cy + radius * Math.sin(angle);
    const x2 = cx + radius * Math.cos(end);
    const y2 = cy + radius * Math.sin(end);
    const path = `M${cx},${cy} L${x1},${y1} A${radius},${radius} 0 ${large} 1 ${x2},${y2} Z`;
    nodes.push(<path key={i} className={palette[i % palette.length]} d={path} />);
    angle = end;
  });
  return <g>{nodes}</g>;
}
