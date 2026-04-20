"use client";

import dynamic from "next/dynamic";
import type { CSSProperties } from "react";
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

  const heightFromFigure =
    typeof fig.layout?.height === "number" ? fig.layout.height : undefined;
  const resolvedHeight = height ?? heightFromFigure;

  const layout: Partial<Layout> = {
    ...fig.layout,
  };

  // Forcing autosize:true was squeezing tall multi-subplot figures into the parent height,
  // stacking every row on top of each other. Respect backend (or prop) pixel height instead.
  if (resolvedHeight !== undefined) {
    layout.height = resolvedHeight;
    layout.autosize = false;
  } else if (layout.autosize === undefined) {
    layout.autosize = true;
  }

  const traces = fig.data ?? [];
  const yAxes = new Set(
    traces.map((t) => (t as { yaxis?: string }).yaxis).filter(Boolean),
  );
  const multiYAxisLayout = yAxes.size > 1;

  const style: CSSProperties = {
    display: "block",
    width: "100%",
    ...(resolvedHeight !== undefined
      ? { height: resolvedHeight, minHeight: resolvedHeight }
      : { minHeight: 360 }),
  };

  return (
    <div className="w-full min-w-0">
      <Plot
        data={fig.data}
        layout={layout}
        useResizeHandler={!multiYAxisLayout}
        style={style}
        config={{ displaylogo: false, responsive: true }}
      />
    </div>
  );
}
