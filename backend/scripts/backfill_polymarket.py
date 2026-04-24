"""
backfill_polymarket.py
----------------------
Fetches all Polymarket token price histories defined in
config/polymarket_markets.yaml, computes signals via signal_builder,
and writes to backend/data/robo_advisor/signals.parquet.

Usage (from repo root):
    cd backend
    uv run python scripts/backfill_polymarket.py

Output:
    - data/robo_advisor/signals.parquet  (written/overwritten)
    - Summary table printed: signal name, date range, row count
    - Warning list of any empty tokens
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow imports from backend/app
sys.path.insert(0, str(Path(__file__).parents[1]))

import logging

from app.robo_advisor.data.loaders.polymarket_loader import PolymarketLoader
from app.robo_advisor.overlay.signal_builder import _load_config, build_signals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_CONFIG = Path(__file__).parents[1] / "config" / "polymarket_markets.yaml"
_OUTPUT = Path(__file__).parents[1] / "data" / "robo_advisor" / "signals.csv"


def _collect_token_ids(config: dict) -> list[str]:
    ids: list[str] = []
    for spec in config["signals"].values():
        if spec["type"] == "binary":
            ids.append(spec["yes_token_id"])
        elif spec["type"] == "multi_outcome_expected_value":
            for outcome in spec["outcomes"]:
                ids.append(outcome["yes_token_id"])
    return ids


def main() -> None:
    config = _load_config(_CONFIG)
    token_ids = _collect_token_ids(config)

    logger.info("Fetching %d tokens from Polymarket CLOB…", len(token_ids))
    loader = PolymarketLoader()
    histories = loader.fetch_many(token_ids)

    empty = [tid[:16] + "…" for tid, df in histories.items() if df.empty]
    if empty:
        logger.warning("Empty tokens (%d): %s", len(empty), empty)

    logger.info("Building signals…")
    signals_df = build_signals(histories, config_path=_CONFIG)

    if signals_df.empty:
        logger.error("No signals built — check token IDs and Polymarket API.")
        sys.exit(1)

    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    signals_df.to_csv(_OUTPUT, index=False)
    logger.info("Wrote %d rows → %s", len(signals_df), _OUTPUT)

    print("\n── Signal summary ──────────────────────────────────")
    for sig_name in signals_df["signal_name"].unique():
        sub = signals_df[signals_df["signal_name"] == sig_name]
        non_nan = sub["value"].notna().sum()
        print(
            f"  {sig_name:<30s}  "
            f"{str(sub['date'].min())} → {str(sub['date'].max())}  "
            f"({non_nan}/{len(sub)} non-NaN rows)"
        )

    if empty:
        print(f"\n  ⚠ {len(empty)} empty token(s): {empty}")
    print()


if __name__ == "__main__":
    main()
