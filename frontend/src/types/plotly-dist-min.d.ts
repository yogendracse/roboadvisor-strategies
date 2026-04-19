declare module "plotly.js-dist-min" {
  import type { PlotlyHTMLElement } from "plotly.js";
  const Plotly: {
    newPlot: (
      ...args: unknown[]
    ) => Promise<PlotlyHTMLElement> | PlotlyHTMLElement;
    react: (...args: unknown[]) => unknown;
    [key: string]: unknown;
  };
  export default Plotly;
}
