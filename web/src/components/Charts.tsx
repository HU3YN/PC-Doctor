// Time-series charts for a run: frame times and sensor readings.
//
// One y-axis per chart (never two scales on one plot): readings with different
// units get their own small chart. A series keeps its color everywhere - CPU
// is always the first color, GPU the second. The crosshair tooltip lists every
// series at that moment, and the statistics table under the charts carries the
// same numbers for anyone who cannot read them off a line.
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Series } from "../api";
import { formatNumber } from "../format";

interface SeriesSpec {
  key: string;
  label: string;
  color: string;
}

function clock(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

interface TipProps {
  active?: boolean;
  label?: number | string;
  payload?: { dataKey?: string | number; value?: number | null }[];
  series: SeriesSpec[];
  unit: string;
}

function ChartTip({ active, label, payload, series, unit }: TipProps) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="chart-tip">
      <div className="when">at {clock(Number(label))}</div>
      {series.map((spec) => {
        const item = payload.find((entry) => entry.dataKey === spec.key);
        if (!item || item.value === null || item.value === undefined) return null;
        return (
          <div className="line" key={spec.key}>
            <span>
              <span className="key" style={{ borderColor: spec.color }} />
              {spec.label}
            </span>
            <b>{formatNumber(item.value, unit)}</b>
          </div>
        );
      })}
    </div>
  );
}

interface TimeChartProps {
  title: string;
  unit: string;
  rows: Record<string, number | null>[];
  series: SeriesSpec[];
  note?: string;
  zeroBased?: boolean;
  limit?: { value: number; label: string };
}

export function TimeChart({ title, unit, rows, series, note, zeroBased, limit }: TimeChartProps) {
  const last = rows.length > 0 ? Number(rows[rows.length - 1]?.t ?? 0) : 0;
  return (
    <div className="card">
      <div className="chart-head">
        <h3>
          {title} <span className="muted small">({unit})</span>
        </h3>
        {/* One series is named by the title; two or more always get a legend. */}
        {series.length > 1 && (
          <div className="legend">
            {series.map((spec) => (
              <span key={spec.key}>
                <span className="key" style={{ borderColor: spec.color }} />
                {spec.label}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="chart" role="img" aria-label={`${title} over the run, in ${unit}`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              domain={[0, last]}
              tickFormatter={clock}
              stroke="var(--axis)"
              tickLine={false}
              tickCount={7}
            />
            <YAxis
              width={46}
              stroke="var(--axis)"
              axisLine={false}
              tickLine={false}
              domain={zeroBased ? [0, "auto"] : ["auto", "auto"]}
              tickFormatter={(value: number) => formatNumber(value)}
            />
            <Tooltip
              content={<ChartTip series={series} unit={unit} />}
              cursor={{ stroke: "var(--axis)", strokeWidth: 1 }}
              isAnimationActive={false}
            />
            {limit && (
              <ReferenceLine
                y={limit.value}
                stroke="var(--axis)"
                strokeDasharray="0"
                label={{ value: limit.label, position: "insideTopRight", fill: "var(--muted)", fontSize: 11 }}
              />
            )}
            {series.map((spec) => (
              <Line
                key={spec.key}
                dataKey={spec.key}
                name={spec.label}
                stroke={spec.color}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
                dot={false}
                activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {note && <p className="muted small">{note}</p>}
    </div>
  );
}

/** Turn column arrays ({t: [...], a: [...]}) into one object per point. */
export function toRows(
  t: number[],
  columns: Record<string, (number | null)[] | undefined>,
): Record<string, number | null>[] {
  return t.map((time, index) => {
    const row: Record<string, number | null> = { t: time };
    for (const [key, values] of Object.entries(columns)) {
      if (values) row[key] = values[index] ?? null;
    }
    return row;
  });
}

// Sensor charts, grouped by unit. Colors follow the part, not the position:
// CPU is always --series-1 and GPU always --series-2.
const SENSOR_CHARTS: { title: string; unit: string; zeroBased?: boolean; series: SeriesSpec[] }[] = [
  {
    title: "Temperatures",
    unit: "°C",
    series: [
      { key: "cpu_temp_c", label: "CPU", color: "var(--series-1)" },
      { key: "gpu_temp_c", label: "GPU", color: "var(--series-2)" },
      { key: "gpu_hotspot_c", label: "GPU hot spot", color: "var(--series-3)" },
    ],
  },
  {
    title: "Load",
    unit: "%",
    zeroBased: true,
    series: [
      { key: "cpu_load_pct", label: "CPU (all cores)", color: "var(--series-1)" },
      { key: "gpu_load_pct", label: "GPU", color: "var(--series-2)" },
      { key: "cpu_core_max_load_pct", label: "Busiest CPU core", color: "var(--series-3)" },
    ],
  },
  {
    title: "Clock speed",
    unit: "MHz",
    series: [
      { key: "cpu_clock_mhz", label: "CPU", color: "var(--series-1)" },
      { key: "gpu_clock_mhz", label: "GPU", color: "var(--series-2)" },
    ],
  },
  {
    title: "CPU speed against its rated speed",
    unit: "%",
    series: [{ key: "cpu_perf_pct", label: "CPU", color: "var(--series-1)" }],
  },
  {
    title: "Power",
    unit: "W",
    zeroBased: true,
    series: [
      { key: "cpu_power_w", label: "CPU", color: "var(--series-1)" },
      { key: "gpu_power_w", label: "GPU", color: "var(--series-2)" },
    ],
  },
  {
    title: "Memory in use",
    unit: "%",
    zeroBased: true,
    series: [
      { key: "ram_used_pct", label: "RAM", color: "var(--series-4)" },
      { key: "gpu_vram_used_pct", label: "Video memory", color: "var(--series-5)" },
    ],
  },
];

export function RunCharts({ series }: { series: Series }) {
  const charts = [];
  const frames = series.frames;
  if (frames && frames.t.length > 1) {
    charts.push(
      <TimeChart
        key="frames"
        title="Frame time"
        unit="ms"
        zeroBased
        rows={toRows(frames.t, { max_ms: frames.max_ms, avg_ms: frames.avg_ms })}
        series={[
          { key: "avg_ms", label: "Average", color: "var(--series-1)" },
          { key: "max_ms", label: "Slowest frame", color: "var(--series-2)" },
        ]}
        note="Lower and flatter is better. Tall orange peaks are the stutters: single frames that took far longer than the ones around them."
      />,
    );
  }
  const sensors = series.sensors;
  if (sensors && sensors.t.length > 1) {
    for (const chart of SENSOR_CHARTS) {
      const present = chart.series.filter((spec) =>
        (sensors[spec.key] ?? []).some((value) => value !== null),
      );
      if (present.length === 0) continue;
      const columns: Record<string, (number | null)[] | undefined> = {};
      for (const spec of present) columns[spec.key] = sensors[spec.key];
      charts.push(
        <TimeChart
          key={chart.title}
          title={chart.title}
          unit={chart.unit}
          zeroBased={chart.zeroBased}
          rows={toRows(sensors.t, columns)}
          series={present}
        />,
      );
    }
  }
  if (charts.length === 0) return null;
  return <div className="stack">{charts}</div>;
}
