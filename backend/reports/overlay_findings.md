# Overlay Findings

Backtest window: January 1, 2015 to April 23, 2026 for the balanced profile.

## Data caveats

- One or more overlay signals are using FRED proxies (confidence 0.70) because Polymarket history is unavailable before September 2025.

## 1. Does overlay improve Sharpe vs core-only? By how much?

Yes. Core Sharpe was 0.909 and core+overlay Sharpe was 0.960, a change of +0.051. Total return moved from 148.36% to 164.61%, adding +16.25%.

## 2. When does overlay help most? (regime analysis)

The overlay helped most during confirmed de-risking regimes, defined here as monthly rebalance dates where the `derisk_recession` breaker was active. Average monthly excess return in those periods was 2.54%. During proxy-driven pre-September 2025 history, average monthly excess was 0.04%; during live Polymarket periods it was 0.13%.

## 3. When does it hurt? (false signals)

The worst monthly false-signal periods were:

- 2016-01: overlay lagged core by -1.33%
- 2022-06: overlay lagged core by -0.70%
- 2017-03: overlay lagged core by -0.59%

These were months where the overlay either de-risked too early or failed to participate fully in risk-on moves.

## 4. What's the turnover cost?

Core gross turnover was 21.98; overlay gross turnover was 27.41, so the overlay added 5.43 of extra turnover. Transaction costs rose from $1,533.93 to $2,007.70.

## 5. Are Polymarket probabilities well-calibrated based on historical resolved markets?

The current repository does not contain resolved-market outcome labels for the three Polymarket contracts, so calibration cannot be estimated robustly from local historical data alone. Any answer here would be speculative.
