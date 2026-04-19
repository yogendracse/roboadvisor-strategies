# Volatility Dashboard

A multi-strategy systematic trading dashboard. Strategies are **plugins**: dropping a new
Python file into [backend/app/strategies/](backend/app/strategies/) makes it discoverable
over HTTP and renderable in the UI — no edits anywhere else.

Currently ships with two strategies:

- **Volatility Analysis** — mean-reversion on rolling-vol z-scores (long low-vol / short
  high-vol quintiles). 5 single-instrument tabs + a multi-instrument summary tab.
- **Trend Following** — four fixed systems (10/30 MA, 30/100 MA, 80/160 MA, 30-day
  breakout) with equal-weight and inverse-volatility portfolio aggregation across a
  basket of assets. 4 tabs.

The original Streamlit prototype lives in [legacy/](legacy/) for reference / side-by-side
comparison.

---

## Architecture

```
┌───────────────────────────────┐        ┌───────────────────────────────┐
│         Next.js 16            │        │         FastAPI               │
│    (app router, React 19)     │◄──────►│                               │
│                               │  HTTP  │  strategy plugin registry     │
│   TanStack Query · Zustand    │        │  Pydantic schemas             │
│   Tailwind · Plotly.js        │        │  pandas / numpy / plotly      │
│                               │        │                               │
│     localhost:3000            │        │     localhost:8787            │
└───────────────────────────────┘        └───────────────────────────────┘
         ▲                                            ▲
         │                                            │
    OpenAPI → TS codegen                 CSVs in backend/data/ + bundled xlsx
```

- **Backend** serves a uniform API for every strategy:
  `POST /api/strategies/{id}/compute` returns metrics + charts + tables + markdown.
  Strategies that implement `compute_summary()` additionally expose
  `POST /api/strategies/{id}/summary` for multi-instrument sweeps.
- **Frontend** is schema-agnostic for results: it renders whatever `tabs`, `charts`, and
  `tables` the strategy emits. Per-strategy **sidebar params** are currently hand-rolled
  (Vol / Trend each have their own component); we'll move to schema-driven forms once
  there's a third strategy to validate against.
- **Charts** are built server-side as Plotly figure JSON and rendered client-side via
  `react-plotly.js` + `plotly.js-dist-min`.

---

## Repo layout

```
Volatility/
├── backend/                              FastAPI service
│   ├── app/
│   │   ├── main.py                       FastAPI app + CORS + router mounts
│   │   ├── api/
│   │   │   ├── health.py                 /api/health
│   │   │   ├── instruments.py            /api/instruments CRUD + yfinance + upload
│   │   │   └── strategies.py             /api/strategies list / schema / compute / summary
│   │   ├── core/
│   │   │   ├── config.py                 Paths, sector list, built-in IDs
│   │   │   ├── palette.py                Chart colour palette
│   │   │   └── registry.py               Auto-discovers strategies/*.py
│   │   ├── schemas/
│   │   │   ├── common.py                 Instrument, InstrumentKind, AddRequest, …
│   │   │   └── results.py                StrategyResult, TabSpec, ChartSpec, TableSpec
│   │   ├── services/
│   │   │   ├── instrument_service.py     Load / save / list / delete instruments
│   │   │   └── metadata_service.py       _metadata.json (sector tags)
│   │   └── strategies/
│   │       ├── base.py                   BaseStrategy ABC
│   │       ├── vol_analysis.py           Vol strategy plugin
│   │       └── trend_following.py        Trend strategy plugin
│   ├── data/                             User-added vol instrument CSVs + sector metadata
│   │   ├── *.csv                         (Date, Close) — one per instrument
│   │   ├── _metadata.json                { "AAPL": { "sector": "Technology" }, … }
│   │   └── trend/*.csv                   User-added trend instrument CSVs
│   ├── SP data.xlsx                      Built-in S&P 500 (1960–2000) for vol strategy
│   ├── TREND_data.xlsx                   Built-in Euro FX / 10Y / S&P 500 (1999–2010) for trend
│   ├── tests/
│   └── pyproject.toml                    uv-managed
│
├── frontend/                             Next.js 16 app
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx                Root layout + React Query provider
│   │   │   ├── page.tsx                  Home — strategy index cards
│   │   │   └── strategies/[id]/
│   │   │       ├── page.tsx              Dynamic strategy route
│   │   │       └── strategy-workspace.tsx    Main shell: picker + params + tabs + results
│   │   ├── components/
│   │   │   ├── charts/PlotlyChart.tsx          Dynamic-imported Plotly renderer
│   │   │   ├── instruments/                    InstrumentPicker + AddInstrumentDialog
│   │   │   ├── strategy/                       Per-strategy params + MetricStrip, TabContent, ResultsTable
│   │   │   └── ui/                             Modal, Tabs, Disclosure, Markdown
│   │   ├── lib/
│   │   │   ├── api.ts                    fetch wrapper + ApiError
│   │   │   ├── instruments.ts            TanStack Query hooks for instruments
│   │   │   ├── strategy-compute.ts       useComputeQuery + useSummaryQuery
│   │   │   ├── strategies.ts             Strategy metadata (hardcoded for now)
│   │   │   ├── store.ts                  Zustand UI state
│   │   │   └── use-debounced-value.ts    Debounce hook
│   │   └── types/
│   │       ├── api.ts                    Auto-generated from backend OpenAPI
│   │       └── plotly-dist-min.d.ts
│   └── package.json
│
├── legacy/                               Original Streamlit prototype (reference)
│   ├── vol_app.py                        2,908-line monolith — source of truth for ports
│   ├── vol_analysis.py
│   └── vol_dashboard.py
│
├── package.json                          Root — concurrent dev script + pnpm workspace
├── pnpm-workspace.yaml
└── pnpm-lock.yaml
```

---

## Getting started

> **Received this as a zip?** The archive ships with **source code, data, and lockfiles
> only** — `node_modules/` and `.venv/` are excluded (they're OS-specific and would
> balloon the zip to ~1.3 GB). Run the **Install** step below once after unzipping to
> rebuild them. The lockfiles guarantee identical dependency versions.

### 1. Prerequisites (one-time per machine)

- **Node 20+** and **pnpm**
  ```bash
  npm install -g pnpm
  ```
- **Python 3.11+** and **uv**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

Verify:
```bash
node --version && pnpm --version && python3 --version && uv --version
```

### 2. Install dependencies (run once after unzip / clone)

```bash
cd Volatility               # the unzipped folder
pnpm install                # frontend deps (~700 MB in frontend/node_modules)
uv sync --directory backend # backend deps (~200 MB in backend/.venv)
```

Both commands read the committed lockfiles (`pnpm-lock.yaml`, `backend/uv.lock`) and
pin you to the exact versions this project was built with.

### 3. Run (dev)

```bash
pnpm dev        # runs backend (:8787) and frontend (:3000) concurrently
```

Or separately:

```bash
pnpm dev:api    # FastAPI with --reload on :8787
pnpm dev:web    # Next.js dev server on :3000
```

Then open **http://localhost:3000**.

### Troubleshooting

- **Port 8787 or 3000 in use** → kill the existing process (`lsof -ti :8787 | xargs kill`) or change the port in [package.json](package.json) → `dev:api` script.
- **`pnpm: command not found`** after install → restart your shell or run `source ~/.zshrc`.
- **`uv: command not found`** → the installer writes to `~/.local/bin`; add it to `PATH` or restart your shell.
- **Frontend can't reach backend** → check that both processes are running and that [frontend/.env.local](frontend/.env.local) points at the right backend URL (default `http://localhost:8787`).

### Regenerate TypeScript types from backend OpenAPI

After adding/changing a backend endpoint or Pydantic model:

```bash
pnpm codegen:api
```

This writes [frontend/src/types/api.ts](frontend/src/types/api.ts) from the running
backend's `/openapi.json`. Requires the backend to be running.

---

## Adding a new strategy

The goal: **one new file → strategy appears in the UI**. Two files in practice (one
backend, one frontend sidebar), and no edits to any existing registry / router /
workspace code.

### 1. Backend — the plugin

Create `backend/app/strategies/my_strategy.py`:

```python
from datetime import date
from typing import ClassVar

import plotly.graph_objects as go
from pydantic import BaseModel, Field

from app.schemas.common import InstrumentKind
from app.schemas.results import (
    ChartSpec, Metric, StrategyResult, TabSpec,
)
from app.services import instrument_service
from app.strategies.base import BaseStrategy


class MyParams(BaseModel):
    instrument_id: str
    date_start: date | None = None
    date_end:   date | None = None
    threshold:  float = Field(default=0.02, ge=0, le=1.0)


class MyStrategy(BaseStrategy):
    id = "my-strategy"
    name = "My Strategy"
    description = "One-sentence elevator pitch."
    instrument_kind = InstrumentKind.vol          # or .trend
    ParamsModel: ClassVar = MyParams
    has_summary = False                            # True if you implement compute_summary

    def compute(self, params: MyParams) -> StrategyResult:
        df = instrument_service.load_instrument_frame(
            InstrumentKind.vol, params.instrument_id,
        )
        # … your pandas/numpy compute here …

        fig = go.Figure(go.Scatter(x=df["Date"], y=df["Close"]))
        return StrategyResult(
            overview_md="**My strategy** — what it does in 2–3 lines.",
            metrics=[
                Metric(key="ret", label="Return", value=0.123, format="percent"),
            ],
            tabs=[
                TabSpec(
                    id="main",
                    title="Overview",
                    icon="📈",
                    intro_md="What to look for in this tab.",
                    charts=[
                        ChartSpec(
                            id="price",
                            title="Price",
                            description="Optional short caption under the title.",
                            guide_md="Optional collapsible 'Plain-language guide'.",
                            figure=json.loads(fig.to_json()),
                        ),
                    ],
                ),
            ],
        )


STRATEGY = MyStrategy()   # ← the registry picks this up
```

That's it on the backend side. The registry auto-discovers the module via
[backend/app/core/registry.py](backend/app/core/registry.py) and the following endpoints
light up immediately:

- `GET  /api/strategies` — includes your new entry
- `GET  /api/strategies/my-strategy/schema` — Pydantic-derived JSON schema
- `POST /api/strategies/my-strategy/compute` — returns your `StrategyResult`

The strategy also shows up on the home page at **http://localhost:3000** as a card
(sourced from the backend list, but currently also hardcoded in
[frontend/src/lib/strategies.ts](frontend/src/lib/strategies.ts) — add it there too until
we switch to the API-driven list).

### 2. Frontend — the params sidebar

Create `frontend/src/components/strategy/MyStrategyParams.tsx` exporting a component that
edits the params object, then add a branch to the dispatcher in
[frontend/src/app/strategies/[id]/strategy-workspace.tsx](frontend/src/app/strategies/[id]/strategy-workspace.tsx):

```tsx
{strategy.id === "my-strategy" && (
  <MyStrategyParams
    value={myParams}
    onChange={setMyParams}
    minDate={activeInst?.min_date}
    maxDate={activeInst?.max_date}
  />
)}
```

Use [VolAnalysisParams.tsx](frontend/src/components/strategy/VolAnalysisParams.tsx) or
[TrendFollowingParams.tsx](frontend/src/components/strategy/TrendFollowingParams.tsx) as
templates. Building blocks in [ParamField.tsx](frontend/src/components/strategy/ParamField.tsx)
(NumberField slider, SelectField, DateRangeField).

> **Roadmap:** once a third strategy exists, we'll generalise the sidebar into a
> schema-driven form (backend already serves the JSON schema; `react-hook-form` + `zod`
> wire-up is prepared). Until then the hand-rolled approach is deliberate — see
> [/.claude/plans/i-have-this-streamlit-cuddly-duckling.md](/.claude/plans/i-have-this-streamlit-cuddly-duckling.md).

### 3. Regenerate TS types and you're done

```bash
pnpm codegen:api
```

The tabs, charts, tables, metrics, markdown narrative, and the reactive/debounced
compute loop all just work — they're schema-agnostic on the frontend.

### Optional — `compute_summary` for multi-instrument sweeps

If your strategy has a portfolio-wide view that's too expensive to run on every slider
drag (e.g. iterates all instruments), set `has_summary = True` on the class and implement:

```python
def compute_summary(self, params: MyParams) -> StrategyResult:
    # iterate instrument_service.list_instruments(self.instrument_kind)
    # return a StrategyResult with a single TabSpec
    ...
```

The frontend automatically adds a **🌐 Summary · All Instruments** tab and only calls
this endpoint when that tab is opened (results cached for 2 minutes).

---

## Adding instruments

Instruments are per-strategy-kind (`vol` or `trend`) and persist as CSVs under
[backend/data/](backend/data/) (vol) or [backend/data/trend/](backend/data/trend/) (trend).
Sector tags for vol instruments live in `_metadata.json`.

Three ways to add one:

1. **UI** — the ➕ Add button in the Instruments panel. yfinance lookup or CSV/Excel
   upload. Sector picker (vol only).
2. **Drop a CSV into [backend/data/](backend/data/)** with `Date,Close` columns. It
   appears on next reload of the instruments list.
3. **API**:
   ```
   POST /api/instruments/yfinance  { ticker, kind, sector? }
   POST /api/instruments/upload     multipart: label, kind, sector?, file
   ```

Built-in instruments (bundled with the repo, not deletable):

- **S&P 500 (built-in)** — vol, from [backend/SP data.xlsx](backend/SP%20data.xlsx), 1960–2000
- **Euro FX / 10-Year Note / S&P 500** — trend, from [backend/TREND_data.xlsx](backend/TREND_data.xlsx), 1999–2010

---

## Result schema (for strategy authors)

`StrategyResult` (backend → frontend) is the contract. Defined in
[backend/app/schemas/results.py](backend/app/schemas/results.py):

```
StrategyResult
  ├── overview_md: str?              top-of-page markdown
  ├── metrics: [Metric]              KPI strip shown above tabs
  ├── tabs: [TabSpec]                ordered list
  │      ├── id, title, icon
  │      ├── intro_md                collapsible "plain-language guide"
  │      ├── metrics: [Metric]       per-tab KPIs (optional)
  │      ├── charts: [ChartSpec]
  │      │       ├── id, title
  │      │       ├── description     short markdown caption under title
  │      │       ├── guide_md        collapsible per-chart guide
  │      │       └── figure          Plotly figure dict — use json.loads(fig.to_json())
  │      └── tables: [TableSpec]
  │              ├── id, title, description
  │              ├── columns: [ColumnSpec]   key, label, format, align
  │              └── rows: [dict]
  └── warnings: [str]
```

`Metric.format`: `"number"`, `"percent"`, `"ratio"`. Controls frontend formatting +
tone colour.

`ColumnSpec.format`: `"text"`, `"number"`, `"percent"`, `"ratio"`, `"date"`.
`ColumnSpec.align`: `"left"` | `"right"`.

---

## Tech stack

| Layer       | Choice                                                                        |
|-------------|-------------------------------------------------------------------------------|
| Backend     | FastAPI, Pydantic v2, pandas, numpy, Plotly, openpyxl, yfinance, diskcache    |
| Backend dev | uv (env + lockfile), uvicorn (`--reload`), ruff, pytest                       |
| Frontend    | Next.js 16 (App Router), React 19, TypeScript 5, Tailwind 4                   |
| Frontend UI | TanStack Query, Zustand, react-plotly.js + plotly.js-dist-min, react-markdown |
| Dev tooling | pnpm workspaces, concurrently, openapi-typescript                             |

---

## Useful commands

```bash
pnpm dev                  # start backend + frontend
pnpm dev:api              # backend only
pnpm dev:web              # frontend only
pnpm codegen:api          # regenerate TS types from backend OpenAPI
pnpm build:web            # production Next build
pnpm lint:web             # ESLint on frontend
uv run --directory backend pytest    # backend tests
uv run --directory backend ruff check .   # backend lint
```

Backend OpenAPI docs: **http://localhost:8787/docs**
