import { useEffect, useRef, useState } from "react";
import Chart from "chart.js/auto";
import { useDarkTheme } from "../../app/theme";
export type Series = {
  id: string;
  name: string;
  points: { x: number; y: number }[];
};
export type ChartSettings = {
  metric: string;
  xAxis: string;
  title: string;
  xLabel: string;
  yLabel: string;
  xScale: "linear" | "logarithmic";
  yScale: "linear" | "logarithmic";
  width: number;
  height: number;
  pixelRatio: number;
  xMin?: number;
  xMax?: number;
  yMin?: number;
  yMax?: number;
};
export const palette = [
  "#4C78A8",
  "#2ca02c",
  "#D45B5B",
  "#F58518",
  "#17BECF",
  "#E377C2",
  "#9467bd",
  "#8C564B",
  "#FF9DA7",
];
export function seriesColors(series: Series[], appearance: Record<string, { color?: string }>) {
  const used = new Set(Object.values(appearance).flatMap(item => item.color ? [item.color.toLowerCase()] : []));
  return series.map((item, index) => {
    if (appearance[item.id]?.color) return appearance[item.id].color!;
    let color = palette.find(value => !used.has(value.toLowerCase()));
    for (let n = index; !color; n++) {
      const hue = (n * 137.508) % 360;
      const rgb = [0, 8, 4].map(offset => {
        const k = (offset + hue / 30) % 12;
        return Math.round(255 * (0.45 - 0.279 * Math.max(-1, Math.min(k - 3, 9 - k, 1))));
      });
      const candidate = '#' + rgb.map(value => value.toString(16).padStart(2, '0')).join('');
      if (!used.has(candidate)) color = candidate;
    }
    used.add(color.toLowerCase());
    return color;
  });
}
export function chartConfiguration(
  series: Series[],
  settings: ChartSettings,
  appearance: Record<string, { name?: string; color?: string; order?: number }> = {},
  dark = false,
) {
  const colors = seriesColors(series, appearance);
  const ink = dark ? "#e1e9f4" : "#666666";
  const fontFamily = '"Hiragino Sans GB", "DejaVu Sans", sans-serif';
  return {
    type: "line" as const,
    data: {
      datasets: series.map((s, i) => ({
        label: appearance[s.id]?.name || s.name,
        data: s.points.filter(
          (p) =>
            Number.isFinite(p.x) &&
            Number.isFinite(p.y) &&
            (settings.xScale !== "logarithmic" || p.x > 0) &&
            (settings.yScale !== "logarithmic" || p.y > 0),
        ).map((p) => ({
          x: settings.xAxis === "tokens" ? p.x / 1_000_000_000 : p.x,
          y: p.y,
        })),
        borderColor: colors[i],
        backgroundColor: colors[i],
        borderWidth: 2.6,
        // The reference plot samples densely; visible markers make sparse runs look like bubbles.
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0,
      })),
    },
    options: {
      animation: false as const,
      responsive: true,
      maintainAspectRatio: false,
      devicePixelRatio: settings.pixelRatio,
      interaction: { mode: "nearest" as const, intersect: false },
      plugins: {
        title: {
          display: !!settings.title,
          text: settings.title,
          color: ink,
          align: "center" as const,
          font: { family: fontFamily, size: 24, weight: "bold" as const },
          padding: { top: 8, bottom: 18 },
        },
        legend: {
          display: false,
        },
        tooltip: {
          titleFont: { family: fontFamily, size: 16 },
          bodyFont: { family: fontFamily, size: 15 },
        },
      },
      scales: {
        x: {
          type: settings.xScale,
          title: { color: ink, display: true, text: settings.xLabel || settings.xAxis, font: { family: fontFamily, size: 17 } },
          min: settings.xMin,
          max: settings.xMax,
          ticks: { color: ink, font: { family: fontFamily, size: 15 } },
          grid: { color: dark ? "#34435a" : "#D7E0EA", lineWidth: 1 },
          border: { color: dark ? "#61738e" : undefined },
        },
        y: {
          type: settings.yScale,
          title: { color: ink, display: true, text: settings.yLabel || settings.metric, font: { family: fontFamily, size: 17 } },
          min: settings.yMin,
          max: settings.yMax,
          ticks: { color: ink, font: { family: fontFamily, size: 15 } },
          grid: { color: dark ? "#34435a" : "#D7E0EA", lineWidth: 1 },
          border: { color: dark ? "#61738e" : undefined },
        },
      },
    },
    plugins: [
      {
        id: "inset-line-legend",
        afterDraw(chart: Chart) {
          const { ctx, chartArea, data } = chart;
          const padding = 12, lineWidth = 32, gap = 12, rowHeight = 27;
          ctx.save();
          ctx.font = `16px ${fontFamily}`;
          ctx.textAlign = "left";
          ctx.textBaseline = "middle";
          const textWidth = Math.min(
            Math.max(0, ...data.datasets.map((dataset) => ctx.measureText(dataset.label || "").width)),
            Math.max(1, chartArea.width - padding * 2 - lineWidth - gap),
          );
          const left = chartArea.right - padding - textWidth - gap - lineWidth;
          ctx.beginPath();
          ctx.rect(chartArea.left, chartArea.top, chartArea.width, chartArea.height);
          ctx.clip();
          data.datasets.forEach((dataset, index) => {
            const y = chartArea.top + padding + rowHeight * (index + 0.5);
            ctx.strokeStyle = String(dataset.borderColor);
            ctx.lineWidth = 2.6;
            ctx.beginPath();
            ctx.moveTo(left, y);
            ctx.lineTo(left + lineWidth, y);
            ctx.stroke();
            ctx.fillStyle = dark ? ink : "#111111";
            ctx.fillText(dataset.label || "", left + lineWidth + gap, y, textWidth);
          });
          ctx.restore();
        },
      },
      {
        id: "white-background",
        beforeDraw(chart: Chart) {
          const { ctx } = chart;
          ctx.save();
          ctx.globalCompositeOperation = "destination-over";
          ctx.fillStyle = dark ? "#1b2433" : "white";
          ctx.fillRect(0, 0, chart.width, chart.height);
          ctx.restore();
        },
      },
      {
        id: "endpoint-labels",
        afterDatasetsDraw(chart: any) {
          const { ctx, chartArea } = chart;
          ctx.save();
          ctx.font = `bold 16px ${fontFamily}`;
          ctx.textBaseline = "middle";
          chart.data.datasets.forEach((dataset: any, index: number) => {
            const meta = chart.getDatasetMeta(index);
            const points = meta.data || [];
            const point = points[points.length - 1];
            if (!point || !dataset.data?.length) return;
            const pos = point.getProps(["x", "y"], true);
            const value = dataset.data[dataset.data.length - 1]?.y;
            if (!Number.isFinite(pos.x) || !Number.isFinite(pos.y) || !Number.isFinite(value)) return;
            const label = Number(value).toPrecision(4);
            const x = Math.min(pos.x + 14, chartArea.right - ctx.measureText(label).width - 3);
            ctx.strokeStyle = dataset.borderColor;
            ctx.fillStyle = dataset.borderColor;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(pos.x, pos.y);
            ctx.lineTo(x, pos.y);
            ctx.stroke();
            ctx.fillText(label, x + 3, pos.y);
          });
          ctx.restore();
        },
      },
    ],
  };
}
export function ExperimentChart({
  series,
  settings,
  appearance = {},
}: {
  series: Series[];
  settings: ChartSettings;
  appearance?: Record<string, { name?: string; color?: string }>;
}) {
  const dark = useDarkTheme();
  const canvas = useRef<HTMLCanvasElement>(null);
  const [compact, setCompact] = useState(() => window.matchMedia("(max-width: 600px)").matches);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 600px)");
    const update = () => setCompact(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!canvas.current) return;
    const config = chartConfiguration(series, settings, appearance, dark);
    if (compact) {
      config.plugins = config.plugins.filter((plugin) => plugin.id !== "inset-line-legend");
      config.options.plugins.title.font.size = 18;
      config.options.scales.x.ticks.font.size = 12;
      config.options.scales.y.ticks.font.size = 12;
      config.options.scales.x.title.font.size = 14;
      config.options.scales.y.title.font.size = 14;
    }
    const chart = new Chart(canvas.current, config);
    return () => chart.destroy();
  }, [series, settings, appearance, compact, dark]);
  return (
    <>
    {compact && <ul className="mobile-chart-legend" aria-label="曲线图例">{series.map((item, index) => <li key={item.id}><i style={{ borderColor: seriesColors(series, appearance)[index] }} />{appearance[item.id]?.name || item.name}</li>)}</ul>}
    <div className="chart" style={{ aspectRatio: `${settings.width} / ${settings.height}` }}>
      <canvas
        ref={canvas}
        aria-label={`${settings.metric} 实验曲线`}
        role="img"
      />
    </div>
    </>
  );
}
export function downloadPng(
  series: Series[],
  settings: ChartSettings,
  appearance: Record<string, { name?: string; color?: string }>,
) {
  const canvas = document.createElement("canvas");
  canvas.width = settings.width;
  canvas.height = settings.height;
  const config = chartConfiguration(series, settings, appearance);
  config.options.responsive = false;
  const chart = new Chart(canvas, config);
  chart.update("none");
  const a = document.createElement("a");
  a.href = chart.toBase64Image("image/png", 1);
  a.download = `${(settings.title || settings.metric).replace(/[\\/:*?"<>|]/g, "_")}.png`;
  a.click();
  chart.destroy();
}
