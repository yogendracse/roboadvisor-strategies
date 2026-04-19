"use client";

import dynamic from "next/dynamic";
import type { Data, Layout } from "plotly.js";

const Plot = dynamic(
  async () => {
    const [{ default: createPlotlyComponent }, { default: Plotly }] =
      await Promise.all([
        import("react-plotly.js/factory"),
        import("plotly.js-dist-min"),
      ]);
    return createPlotlyComponent(
      Plotly as unknown as Parameters<typeof createPlotlyComponent>[0],
    );
  },
  { ssr: false },
);

interface PlotlyFigure {
  data: Data[];
  layout: Partial<Layout>;
  frames?: unknown[];
}

interface Props {
  figure: unknown;
  height?: number;
}

export function PlotlyChart({ figure, height }: Props) {
  const fig = figure as PlotlyFigure;
  if (!fig || !fig.data) return null;

  const layout: Partial<Layout> = {
    ...fig.layout,
    autosize: true,
    ...(height ? { height } : {}),
  };

  return (
    <Plot
      data={fig.data}
      layout={layout}
      useResizeHandler
      style={{ width: "100%", height: height ? `${height}px` : "100%" }}
      config={{ displaylogo: false, responsive: true }}
    />
  );
}
