import { useEffect, useRef } from "react";
import Chart from "chart.js/auto";
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
  "#F58518",
  "#54A24B",
  "#E45756",
  "#72B7B2",
  "#B279A2",
  "#FF9DA6",
  "#9D755D",
  "#BAB0AC",
  "#2F4B7C",
  "#00A6A6",
  "#D45087",
];
function colorFor(series: Series, index: number, appearance: Record<string, { name?: string; color?: string }>) {
  if (appearance[series.id]?.color) return appearance[series.id]!.color!;
  const used = new Set<string>();
  for (const item of Object.values(appearance)) if (item.color) used.add(item.color.toLowerCase());
  for (let i = 0; i < palette.length; i++) {
    const color = palette[(index + i) % palette.length];
    if (!used.has(color.toLowerCase())) return color;
  }
  const hue = (index * 137.508) % 360;
  return `hsl(${hue} 62% 45%)`;
}
export function chartConfiguration(
  series: Series[],
  settings: ChartSettings,
  appearance: Record<string, { name?: string; color?: string; order?: number }> = {},
) {
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
        ),
        borderColor: colorFor(s, i, appearance),
        backgroundColor: colorFor(s, i, appearance),
        borderWidth: 2.6,
        pointRadius: 3.5,
        pointHoverRadius: 5,
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
          align: "start" as const,
          font: { size: 20, weight: "bold" as const },
        },
        legend: {
          position: "top" as const,
          align: "end" as const,
          labels: { usePointStyle: true, boxWidth: 7, padding: 24 },
        },
      },
      scales: {
        x: {
          type: settings.xScale,
          title: { display: true, text: settings.xLabel || settings.xAxis },
          min: settings.xMin,
          max: settings.xMax,
          grid: { color: "#D7E0EA" },
        },
        y: {
          type: settings.yScale,
          title: { display: true, text: settings.yLabel || settings.metric },
          min: settings.yMin,
          max: settings.yMax,
          grid: { color: "#D7E0EA" },
        },
      },
    },
    plugins: [
      {
        id: "white-background",
        beforeDraw(chart: Chart) {
          const { ctx } = chart;
          ctx.save();
          ctx.globalCompositeOperation = "destination-over";
          ctx.fillStyle = "white";
          ctx.fillRect(0, 0, chart.width, chart.height);
          ctx.restore();
        },
      },
      {
        id: "endpoint-labels",
        afterDatasetsDraw(chart: any) {
          const { ctx, chartArea } = chart;
          ctx.save();
          ctx.font = "12px DejaVu Sans, sans-serif";
          ctx.textBaseline = "middle";
          chart.data.datasets.forEach((dataset: any, index: number) => {
            const meta = chart.getDatasetMeta(index);
            const points = meta.data || [];
            const point = points[points.length - 1];
            if (!point || !dataset.data?.length) return;
            const pos = point.getProps(["x", "y"], true);
            const value = dataset.data[dataset.data.length - 1]?.y;
            if (!Number.isFinite(pos.x) || !Number.isFinite(pos.y) || !Number.isFinite(value)) return;
            const x = Math.min(pos.x + 14, chartArea.right - 48);
            ctx.strokeStyle = dataset.borderColor;
            ctx.fillStyle = dataset.borderColor;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(pos.x, pos.y);
            ctx.lineTo(x, pos.y);
            ctx.stroke();
            ctx.fillText(Number(value).toPrecision(4), x + 3, pos.y);
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
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!canvas.current) return;
    const chart = new Chart(
      canvas.current,
      chartConfiguration(series, settings, appearance),
    );
    return () => chart.destroy();
  }, [series, settings, appearance]);
  return (
    <div className="chart">
      <canvas
        ref={canvas}
        aria-label={`${settings.metric} 实验曲线`}
        role="img"
      />
    </div>
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
