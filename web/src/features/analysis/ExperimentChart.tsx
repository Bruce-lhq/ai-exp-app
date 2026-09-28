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
  "#2861dc",
  "#dc763b",
  "#26a08c",
  "#9367cb",
  "#ce5b86",
  "#6b8a32",
];
export function chartConfiguration(
  series: Series[],
  settings: ChartSettings,
  appearance: Record<string, { name?: string; color?: string }> = {},
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
        borderColor: appearance[s.id]?.color || palette[i % palette.length],
        backgroundColor: appearance[s.id]?.color || palette[i % palette.length],
        borderWidth: 2,
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
          font: { size: 16 },
        },
        legend: {
          position: "bottom" as const,
          labels: { usePointStyle: true, boxWidth: 7, padding: 24 },
        },
      },
      scales: {
        x: {
          type: settings.xScale,
          title: { display: true, text: settings.xLabel || settings.xAxis },
          min: settings.xMin,
          max: settings.xMax,
          grid: { color: "#eef1f5" },
        },
        y: {
          type: settings.yScale,
          title: { display: true, text: settings.yLabel || settings.metric },
          min: settings.yMin,
          max: settings.yMax,
          grid: { color: "#eef1f5" },
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
