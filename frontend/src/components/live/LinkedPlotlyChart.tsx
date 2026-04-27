"use client";

import dynamic from "next/dynamic";
import { useCallback, useMemo, useRef } from "react";
import type { Data, Layout } from "plotly.js";

import { useLiveStore } from "@/lib/store";

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
  /** When true this chart participates in the shared x-axis sync */
  syncXAxis?: boolean;
}

/**
 * A Plotly chart that optionally participates in a shared x-axis zoom/pan.
 *
 * All charts with syncXAxis=true on the /live page share the same
 * xaxis.range from the Zustand liveXRange slice. When the user pans or
 * zooms any one chart, all others update to match.
 */
export function LinkedPlotlyChart({ figure, height, syncXAxis = false }: Props) {
  const fig = figure as PlotlyFigure;
  const xRange = useLiveStore((s) => s.liveXRange);
  const setXRange = useLiveStore((s) => s.setLiveXRange);

  // Guard against re-entrant relayout calls: when we update xRange in Zustand,
  // Plotly may fire another relayout from the prop change — skip those.
  const syncingRef = useRef(false);

  const handleRelayout = useCallback(
    (event: Record<string, unknown>) => {
      if (!syncXAxis) return;
      if (syncingRef.current) return;

      const r0 = event["xaxis.range[0]"];
      const r1 = event["xaxis.range[1]"];
      if (r0 !== undefined && r1 !== undefined) {
        syncingRef.current = true;
        setXRange([String(r0), String(r1)]);
        setTimeout(() => {
          syncingRef.current = false;
        }, 100);
      } else if (event["xaxis.autorange"] === true) {
        syncingRef.current = true;
        setXRange(null);
        setTimeout(() => {
          syncingRef.current = false;
        }, 100);
      }
    },
    [syncXAxis, setXRange],
  );

  const layout = useMemo((): Partial<Layout> => {
    const base: Partial<Layout> = {
      ...fig?.layout,
      autosize: true,
      ...(height ? { height } : {}),
    };
    if (syncXAxis && xRange) {
      return {
        ...base,
        xaxis: {
          ...(fig?.layout?.xaxis ?? {}),
          range: xRange,
          autorange: false,
        },
      };
    }
    return base;
  }, [fig, height, syncXAxis, xRange]);

  if (!fig || !fig.data) return null;

  return (
    <Plot
      data={fig.data}
      layout={layout}
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      onRelayout={handleRelayout as any}
      useResizeHandler
      style={{ width: "100%", height: height ? `${height}px` : "100%" }}
      config={{ displaylogo: false, responsive: true }}
    />
  );
}
