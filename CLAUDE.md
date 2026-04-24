# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Dev commands

```bash
# Run everything (FastAPI on :8787 + Next.js on :3000)
pnpm dev

# Backend only
pnpm dev:api          # uv run uvicorn app.main:app --reload --port 8787

# Frontend only
pnpm dev:web

# Frontend build / lint
pnpm build:web
pnpm lint:web

# Regenerate frontend types from live OpenAPI spec (backend must be running)
pnpm codegen:api      # writes frontend/src/types/api.ts

# Run backend tests (pytest, from backend/)
uv run pytest

# Robo-advisor data pipeline (run from backend/)
FRED_API_KEY=<key> uv run python -c "from app.robo_advisor.data.loaders.fred_loader import MacroLoader; MacroLoader().refresh()"
uv run python scripts/backfill_polymarket.py   # fetches 20 Polymarket tokens → signals.csv

# Backend deps are managed by uv; frontend by pnpm workspaces
```

---

## Architecture

```
Next.js 16 (app router) ←HTTP→ FastAPI
localhost:3000                   localhost:8787
```

The two services are independent processes started together by `pnpm dev` via `concurrently`.

### Backend

**Strategy plugin system** — the most important pattern in the codebase.

1. Drop a Python file in `backend/app/strategies/`.
2. Subclass `BaseStrategy` (`app/strategies/base.py`), declare a Pydantic `ParamsModel`, implement `compute(params) → StrategyResult`.
3. Set `STRATEGY = MyStrategy()` at module level.
4. `app/core/registry.py` auto-discovers it via `pkgutil`; `_discover()` is `@lru_cache`-wrapped so it runs once per process.
5. The universal endpoint `POST /api/strategies/{id}/compute` validates params with Pydantic and calls `strategy.compute(parsed)` — no changes to any other file needed.

**StrategyResult schema** (`app/schemas/results.py`) — everything a strategy can return:
- `overview_md` — markdown shown above tabs
- `metrics` — global metric strip
- `tabs: list[TabSpec]` — each tab has `metrics`, `charts`, `tables`, `intro_md`
- `ChartSpec.figure` — raw Plotly figure JSON (`json.loads(fig.to_json())`)
- `TableSpec` with typed `ColumnSpec` columns (`format`: `"number" | "percent" | "ratio" | "date" | "text"`)

**Charts are built server-side** as Plotly figure dicts and sent to the client as JSON. Use `plotly.graph_objects` + `plotly.subplots.make_subplots`; always end with `json.loads(fig.to_json())`.

**Data layout**:
- `backend/data/*.csv` — vol instruments (Date, Close)
- `backend/data/trend/*.csv` — trend instruments (Date, Close)
- `backend/data/live/*.csv` — live signal cache
- `backend/data/counter-trend/COUNTER_TREND_DATA.xlsx` — bundled OHLC for counter-trend strategy
- `backend/data/robo_advisor/macro.csv` — FRED macro series (6 series, 2000-present, ~27k rows)
- `backend/data/robo_advisor/signals.csv` — Polymarket signals (476 rows, Sep 2025-present)
- `backend/data/robo_advisor/prices.csv` — yfinance OHLCV for default universe (written on demand)
- `backend/SP data.xlsx` — S&P 500 1960–2000 (vol strategy built-in)
- `backend/TREND_data.xlsx` — Euro FX / 10Y / S&P 500 1999–2010 (trend built-in)
- `backend/data/_metadata.json` — sector tags keyed by instrument label

**InstrumentKind** (`app/schemas/common.py`) — `vol` or `trend`. Controls which data directory `instrument_service` reads and which picker the frontend shows. The `counter-trend` strategy uses `InstrumentKind.trend` but ignores the instrument catalogue (data is bundled).

**Robo-advisor module** (`backend/app/robo_advisor/`):
- `data/loaders/yfinance_loader.py` — downloads OHLCV → `prices.csv` (incremental)
- `data/loaders/fred_loader.py` — downloads FRED series → `macro.csv`; schema includes `as_of_date` (release date, not observation date) for lookahead-bias prevention in backtests
- `data/loaders/polymarket_loader.py` — fetches Polymarket CLOB price histories (rate-limited 2 req/s)
- `data/loaders/harmonizer.py` — merges Polymarket + FRED into `HarmonizedSignal` list; Polymarket (confidence=1.0) takes priority over FRED proxy (0.70) per (date, signal_name)
- `overlay/signal_builder.py` — builds named signals from token histories per `config/polymarket_markets.yaml`
- **Path constraint**: all loaders use `Path(__file__).parents[4]` for the backend root — that resolves to `backend/`. Do NOT use `parents[5]` (that's workspace root).

**Signal config**: `backend/config/polymarket_markets.yaml` — declares 3 signals with 20 token IDs:
- `recession_prob` — binary, YES-token probability
- `fed_cuts_expected` — multi-outcome EV: `E[X] = sum(midpoint_i * P_yes_i) / sum(P_yes_i)`
- `sp500_close_expected` — multi-outcome EV with price midpoints

**FRED series** (in `macro.csv`): `RECPROUSM156N`, `VIXCLS`, `DGS10`, `DGS2`, `FEDFUNDS`, `T10Y2Y`. Requires `FRED_API_KEY` env var (stored in `backend/.env`, not committed).

**Other API routers**: `health`, `instruments` (CRUD + yfinance + upload), `live`, `simulator`, `robo_advisor` (prices / macro / signals CRUD + background refresh).

### Frontend

**Schema-driven rendering** — `strategy-workspace.tsx` is the main shell. It builds a `computeBody`, fires `useComputeQuery`, and passes the result to `TabContent`. The frontend renders whatever `tabs`, `charts`, and `tables` the backend emits — no frontend changes needed for new tab content.

**Per-strategy params components** (`frontend/src/components/strategy/`) are hand-rolled and wired into `strategy-workspace.tsx`. When adding a new strategy you need:
1. A `*Params.tsx` component + `default*Params` export
2. A `computeBody` branch in `strategy-workspace.tsx`
3. An entry in `frontend/src/lib/strategies.ts` (hardcoded list, not loaded from API)

**Types**: `frontend/src/types/api.ts` is auto-generated from the backend OpenAPI spec via `pnpm codegen:api`. `InstrumentKind` in the frontend is derived from this generated type — changing the backend enum requires regenerating.

**State**: Zustand (`lib/store.ts`) holds `activeInstrumentId` per kind, date ranges, and live-signals state. TanStack Query handles all server state with `staleTime` caching.

**Charts**: Plotly rendered client-side via `react-plotly.js` / `plotly.js-dist-min`, dynamically imported in `PlotlyChart.tsx` to avoid SSR issues.

**Next.js version warning**: This repo uses a version of Next.js with breaking changes. Read `node_modules/next/dist/docs/` before writing routing or server-component code.

---

## Existing strategies

| ID | File | Tabs | Notes |
|---|---|---|---|
| `vol-analysis` | `vol_analysis.py` | 5 + summary | Single-instrument vol z-score mean-reversion |
| `trend-following` | `trend_following.py` | 4 | Multi-asset MA crossover + breakout systems |
| `counter-trend` | `counter_trend.py` | 6 | Bundled XLSX; no instrument picker |

---

## Key constraints

- **Strategy registry is `lru_cache`-wrapped** — restart the backend after adding/renaming a strategy file.
- **Roll-adjusted futures data** in `COUNTER_TREND_DATA.xlsx`: `PrvHiWRoll[t] = (High[t-1] + Roll[t-1])`. Roll column is 0 on non-roll days.
- **`_metadata.json`** is keyed by instrument *label*, not ID — the label is the display name (e.g. `"AAPL"`).
- **CORS** allows only `localhost:3000`; update `app/main.py` if the frontend port changes.
- **`format` field in `ColumnSpec` / `Metric`** controls frontend display: `"percent"` multiplies by 100 and adds `%`; `"ratio"` shows raw float; `"number"` formats with commas.
- **Robo-advisor path rule**: all loaders under `app/robo_advisor/` must use `Path(__file__).parents[4]` to reach `backend/`. `parents[5]` resolves to workspace root — different directory, files not found.
- **Robo-advisor data is CSV not Parquet** — intentional for inspectability. `macro.csv`, `signals.csv`, `prices.csv` all live in `backend/data/robo_advisor/`.
- **`signals.csv` is not committed** — generated by `scripts/backfill_polymarket.py`. Re-run it if stale (Polymarket data only goes back to Sep 2025).
- **`macro.csv` is not committed** — requires `FRED_API_KEY` (in `backend/.env`). Re-run `MacroLoader().refresh()` to update.
