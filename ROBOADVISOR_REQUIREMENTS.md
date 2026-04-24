# Robo-Advisor with Prediction Market Overlay — Requirements

## 1. Project Overview

Build a robo-advisor that combines a **strategic multi-strategy core portfolio** with a **tactical overlay driven by prediction market signals** (Kalshi / Polymarket). The system should support backtesting, live recommendations, risk management, and a user-facing interface.

**Key differentiator:** Prediction market probabilities (e.g., P(recession), P(Fed cuts rates)) are used as a tactical tilt on top of a strategic allocation.

---

## 2. Goals & Non-Goals

### Goals
- Produce a recommended portfolio given a user's risk profile and capital
- Blend multiple strategies (MVO, Risk Parity, Factor) into a core allocation
- Apply a prediction-market-driven tactical overlay
- Backtest and evaluate performance vs. benchmarks (60/40, SPY)
- Implement rebalancing and risk controls
- Expose the system via a simple UI

### Non-Goals (v1)
- No live brokerage execution (Alpaca/IBKR integration is v2)
- No tax-loss harvesting
- No user authentication / multi-tenant accounts
- No options or derivatives

---

## 3. Functional Requirements

### 3.1 Data Layer
- **Price data**: Daily OHLCV for all assets (ETFs, stocks, commodities)
  - Source: `yfinance` (free) or Polygon.io (paid, optional)
  - Store locally in Parquet or SQLite
- **Fundamental data** (for factor model): P/B, P/E, market cap, momentum
- **Prediction market data**: Daily probability snapshots
  - Source: Kalshi API (primary), Polymarket API (fallback)
  - Track at minimum: P(US recession, current year), P(Fed cut next meeting), P(S&P up year-end)
- **Macro data** (optional v2): VIX, yield curve, DXY

### 3.2 Asset Universe
Three sleeves:

| Sleeve | Instruments |
|---|---|
| Core Macro ETFs | SPY/VOO, QQQ, TLT, IEF, GLD, DBC, VNQ, VXUS |
| Equity Alpha (Stocks) | S&P 500 constituents (configurable) |
| Tactical Overlay | Applied across both above sleeves |

### 3.3 Strategy Engine

Each strategy must implement a common interface:
```python
class Strategy:
    def compute_target_weights(self, date, universe, data) -> dict[str, float]
```

Required strategies:
1. **Mean-Variance Optimization (MVO)**
   - Ledoit-Wolf shrinkage for covariance
   - Long-only, fully invested constraints
   - Configurable target return or max Sharpe
2. **Risk Parity**
   - Inverse-volatility or equal risk contribution
3. **Factor Model (Fama-French 3 + Momentum)**
   - For the stock sleeve only
   - Tilt toward value, small-cap, and momentum factors
4. **Strategy Blender**
   - Combine strategy outputs via user-configurable weights (e.g., 50% MVO / 50% Risk Parity)

### 3.4 Prediction Market Overlay

**Core formula:**
```
tilt_i = sensitivity_i × (P_market − P_baseline)
```

Required components:
1. **Signal ingestion**: Pull current probabilities from Kalshi API
2. **Baseline calculation**: Rolling historical median (e.g., trailing 2-year)
3. **Sensitivity mapping**: Config file that maps events → asset tilts

   Example config:
   ```yaml
   signals:
     recession_prob:
       event_id: "RECESSION-26"
       baseline: 0.15
       tilts:
         VOO: -1.5    # beta to recession risk
         TLT: +1.0
         GLD: +0.5
         XLP: +0.3
     fed_cut_prob:
       event_id: "FED-CUT-NEXT"
       baseline: 0.50
       tilts:
         TLT: +0.8
         QQQ: +0.4
   ```
4. **Overlay application**: Apply tilts to core weights, cap total deviation (e.g., ±20% per asset)
5. **De-risking AND re-risking rules**: Critical — must include both directions
   - De-risk when P spikes above baseline + threshold
   - Re-risk when P falls OR when drawdown already prices it in (e.g., use VIX z-score)

### 3.5 Portfolio Construction
- Take blended core weights + overlay tilts → final target weights
- Apply constraints: no short (v1), max position size (e.g., 25%), min position (e.g., 1%)
- Round to tradeable share counts given current prices and capital

### 3.6 Backtesting Engine
- Walk-forward testing with configurable rebalance frequency (daily/weekly/monthly)
- Handle transaction costs (default: 5 bps per trade)
- Produce time series of:
  - Portfolio value
  - Holdings over time
  - Overlay tilts applied
  - Trade log
- Compare vs. benchmarks: SPY, 60/40 (60% VOO, 40% TLT), equal-weight core

### 3.7 Performance & Risk Metrics
- Returns: CAGR, total return, monthly/annual breakdown
- Risk-adjusted: Sharpe, Sortino, Calmar
- Drawdown: Max drawdown, drawdown duration, underwater curve
- Risk: Volatility, VaR (95%, 99%), CVaR
- Attribution: Core strategy contribution vs. overlay contribution

### 3.8 Risk Management & Rebalancing
- **Rebalancing rules**:
  - Calendar-based (monthly/quarterly)
  - Threshold-based (drift > 5% from target)
- **Circuit breakers**:
  - Max portfolio drawdown stop (e.g., -15% → move to cash)
  - Overlay limit (overlay cannot shift weights by more than ±20% from core)

### 3.9 User Interface
- Risk profile questionnaire → maps to strategy mix (conservative/balanced/aggressive)
- Current recommended portfolio with weights and dollar amounts
- Backtest results dashboard with equity curve, metrics, drawdown
- Prediction market signal panel (current probabilities, active tilts)
- Rebalance trigger (generate trade list)

---

## 4. Non-Functional Requirements
- **Language**: Python 3.11+
- **Modularity**: Clear separation between data, strategy, overlay, portfolio, backtest, UI
- **Testing**: Unit tests for each strategy and the overlay logic; integration test for full backtest
- **Reproducibility**: Seeded random state; locked dependency versions (uv or poetry)
- **Documentation**: Docstrings + README with setup, run, and extend instructions
- **Config-driven**: Strategies, sensitivities, and universe defined in YAML, not hardcoded

---

## 5. Tech Stack

| Component | Library |
|---|---|
| Data | `yfinance`, `pandas`, `requests` (Kalshi API) |
| Optimization | `cvxpy`, `scipy`, `scikit-learn` (Ledoit-Wolf) |
| Backtesting | `vectorbt` OR custom (simpler, more transparent) |
| Metrics | `empyrical`, `quantstats` |
| Backend | `FastAPI` |
| Frontend | `Streamlit` (v1), React (v2) |
| Storage | SQLite + Parquet |
| Testing | `pytest` |
| Config | `pydantic`, YAML |

Add to dependencies:
- `fredapi` — FRED macro data (free, API key required)
- `httpx` — async HTTP for Kalshi / Polymarket / FRED REST calls

---

## 6. Project Structure

```
roboadvisor/
├── config/
│   ├── universe.yaml
│   ├── strategies.yaml
│   └── signals.yaml
├── data/
│   ├── loaders/
│   │   ├── yfinance_loader.py
│   │   ├── kalshi_loader.py
│   │   ├── polymarket_loader.py
│   │   ├── fred_loader.py          # NEW — macro proxies via fredapi
│   │   └── harmonizer.py           # NEW — maps proxy signals → unified schema
│   └── storage/          # parquet, sqlite
├── strategies/
│   ├── base.py
│   ├── mvo.py
│   ├── risk_parity.py
│   ├── factor.py
│   └── blender.py
├── overlay/
│   ├── signals.py        # pull from prediction markets
│   ├── mapping.py        # signal → tilt
│   └── rules.py          # de-risk / re-risk rules
├── portfolio/
│   ├── constructor.py
│   └── rebalancer.py
├── backtest/
│   ├── engine.py
│   └── metrics.py
├── risk/
│   └── controls.py
├── api/                  # FastAPI
├── ui/                   # Streamlit
├── tests/
├── pyproject.toml
└── README.md
```

---

## 7. Historical Data Strategy for Backtesting

> **Critical constraint**: Kalshi launched in 2021; Polymarket has limited liquidity before 2022.
> Useful prediction market history is < 4 years — insufficient for a robust walk-forward backtest.
> Solution: a three-layer hybrid approach.

### 7.1 Layer 1 — Long Backtest (2000–present) using Proxy Signals

Use well-established, freely available macro indicators as probabilistic proxies for the same underlying risks that prediction markets price. These are mapped through the harmonizer into the same signal schema used by real prediction market data.

| Signal | Proxy Source | FRED Series / Ticker | Notes |
|---|---|---|---|
| P(recession) | NY Fed recession probability model | `RECPROUSM156N` | Monthly, released with ~1-month lag |
| P(Fed rate cut) | Fed Funds futures implied probability | CME FedWatch (scraped or commercial) | Daily; proxy with 30-day FF futures spread |
| P(market stress) | VIX level / SPX skew | `^VIX` via yfinance | Normalize to [0,1] via rolling percentile |
| P(macro expansion) | ISM / SPF survey expectations | Philly Fed Survey of Professional Forecasters | Quarterly; interpolate to monthly |

**Key design rule**: proxies must be available *as of* the signal date without lookahead bias (use release dates, not reference dates).

### 7.2 Layer 2 — Short Backtest (2022–present) using Actual Prediction Market Data

- **Kalshi REST API**: Pull historical contract prices for recession, Fed, election markets
- **Polymarket subgraph**: GraphQL fallback for overlapping markets
- **Iowa Electronic Markets**: Historical election contract data (academic, free)

Purpose: validate that the proxy signals and real prediction market signals produce similar overlay tilts over the overlapping period. If they diverge materially, document why and adjust proxy calibration.

### 7.3 Layer 3 — Event Studies

Run 20–30 targeted studies around major macro events:

- FOMC meetings (rate decisions, surprise vs. consensus)
- Recession start/end dates (NBER)
- Geopolitical shocks (COVID March 2020, GFC 2008, 9/11)
- Election outcomes (2000, 2004, 2008, 2012, 2016, 2020, 2024)

For each event, measure:
- Overlay tilt magnitude and direction at event date
- Portfolio return in ±5, ±10, ±20 trading days
- Comparison: overlay on vs. off, vs. 60/40 benchmark

### 7.4 Signal Harmonizer

The harmonizer (`data/loaders/harmonizer.py`) is the key abstraction. It ensures the backtest engine never knows whether a signal came from Kalshi or a FRED proxy:

```python
class HarmonizedSignal(BaseModel):
    date: date
    signal_id: str          # e.g. "recession_prob", "fed_cut_prob"
    probability: float      # always in [0, 1]
    source: Literal["kalshi", "polymarket", "fred_proxy", "cme_proxy", "spf_proxy"]
    confidence: float       # 1.0 for real markets; lower for proxies
```

The backtest engine accepts `list[HarmonizedSignal]` regardless of source, making it trivial to swap proxy data for real data as availability grows.

### 7.5 New Data Sources

| Source | Library / Method | Cost | Notes |
|---|---|---|---|
| FRED | `fredapi` | Free (API key) | `RECPROUSM156N`, yield curve, etc. |
| NY Fed recession model | CSV download | Free | Monthly CSV at newyorkfed.org |
| CME FedWatch historical | Scrape / Quandl | Free/paid | 30-day FF futures spread as proxy |
| Kalshi REST API | `httpx` | Free (rate-limited) | `GET /v2/markets/{ticker}/history` |
| Polymarket | GraphQL subgraph | Free | Limited depth pre-2022 |
| Iowa Electronic Markets | CSV download | Free | Historical election contracts |

---

## 8. Build Order (Updated Milestones)

> M1 is expanded; M6 now has two sub-phases. All other milestones are unchanged.

1. **M1 — Data Pipeline** *(expanded)*
   - 1a: yfinance OHLCV loader + local Parquet/SQLite storage
   - 1b: FRED loader (`fredapi`) for macro proxies — recession prob, VIX, yield curve
   - 1c: Kalshi REST + Polymarket GraphQL loaders for real prediction market data
   - 1d: Signal harmonizer — maps all sources to `HarmonizedSignal` schema
   - 1e: Proxy validation notebook — plot proxy vs. real signal over 2022–present overlap

2. **M2 — Core Strategies**: MVO (Ledoit-Wolf) + Risk Parity with tests

3. **M3 — Factor Model**: Fama-French 3-factor + Momentum for stock sleeve

4. **M4 — Strategy Blender + Portfolio Constructor**: Produce target weights

5. **M5 — Backtesting Engine**: Walk-forward, transaction costs, metrics

6. **M6 — Overlay Engine** *(two phases)*
   - 6a: Signal ingestion using `HarmonizedSignal` (source-agnostic)
   - 6b: Sensitivity mapping + de-risk/re-risk rules

7. **M7 — Risk Management**: Rebalancing rules, circuit breakers

8. **M8 — UI**: Streamlit dashboard

9. **M9 — Validation** *(expanded)*
   - Full 2000–present backtest using proxy signals
   - 2022–present overlay using real Kalshi data
   - Event study analysis (20–30 events)
   - Overlay on vs. off vs. 60/40 vs. SPY comparison

---

## 9. Key Assumptions to Test (Updated)

1. **Signal efficacy**: Does the overlay improve risk-adjusted returns vs. core-only?
2. **Proxy calibration**: Do FRED/CME proxies track actual Kalshi probabilities over the 2022–present overlap?
3. **Lead/lag**: Does prediction market move before, with, or after equity markets? Do proxies exhibit the same lead/lag?
4. **Transaction costs**: At what turnover does the overlay stop adding value?
5. **Regime stability**: Does the signal→asset mapping (betas) hold across regimes (2000–2008, 2009–2019, 2020–present)?
6. **Lookahead cleanliness**: Are all proxy signals constructed using only release-date-available data?

---

## 10. Stretch Goals (v2)
- Live brokerage integration (Alpaca paper trading first)
- Tax-loss harvesting
- Multi-user support with auth
- Additional signal sources: news sentiment, Google Trends, options skew
- Regime detection layer (HMM) to switch strategy weights
- React frontend replacing Streamlit
