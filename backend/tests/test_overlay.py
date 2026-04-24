from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.robo_advisor.overlay import build_overlay_preview
from app.robo_advisor.overlay.constructor import apply_overlay
from app.robo_advisor.overlay.mapping import compute_tilts
from app.robo_advisor.overlay.rules import apply_circuit_breakers
from app.robo_advisor.overlay.signal_builder import build_signals


def test_signal_builder_computes_deviation_and_z(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.date_range("2026-01-01", periods=95, freq="D")
    recession = [0.10] * 90 + [0.12, 0.13, 0.14, 0.15, 0.30]
    fed = [2.0] * 95
    spx = [5500.0] * 95
    df = pd.DataFrame(
        {
            "date": list(dates.date) * 3,
            "signal_name": (["recession_prob"] * 95) + (["fed_cuts_expected"] * 95) + (["sp500_close_expected"] * 95),
            "value": recession + fed + spx,
            "source": ["polymarket"] * 285,
            "confidence": [1.0] * 285,
        }
    )

    monkeypatch.setattr(
        "app.robo_advisor.overlay.signal_builder._load_signal_history",
        lambda as_of_date: df[df["date"] <= as_of_date].copy(),
    )

    signals = build_signals(date(2026, 4, 5))
    recession_signal = signals["recession_prob"]
    assert recession_signal["value"] == pytest.approx(0.30)
    assert recession_signal["baseline"] == pytest.approx(0.10)
    assert recession_signal["deviation"] == pytest.approx(0.20)
    assert recession_signal["z"] > 2.0


def test_mapping_uses_signal_deviation() -> None:
    tilts = compute_tilts(
        {
            "recession_prob": {
                "value": 0.20,
                "baseline": 0.10,
                "deviation": 0.10,
                "z": 1.0,
            }
        }
    )
    assert tilts["SPY"] == pytest.approx(-0.15)


def test_circuit_breaker_zeroes_tilts_below_threshold() -> None:
    state = {
        "signals": {
            "recession_prob": {
                "value": 0.20,
                "baseline": 0.10,
                "deviation": 0.10,
            }
        },
        "vix_zscore": 1.5,
        "recession_history": pd.DataFrame(columns=["date", "value"]),
    }
    adjusted = apply_circuit_breakers({"SPY": -0.10, "TLT": 0.05}, state)
    assert adjusted == {"SPY": 0.0, "TLT": 0.0}


def test_circuit_breaker_applies_overlay_budget_cap() -> None:
    state = {
        "signals": {
            "recession_prob": {
                "value": 0.40,
                "baseline": 0.10,
                "deviation": 0.30,
            }
        },
        "vix_zscore": 2.0,
        "recession_history": pd.DataFrame(columns=["date", "value"]),
    }
    adjusted = apply_circuit_breakers({"SPY": -0.20, "TLT": 0.20, "GLD": 0.10}, state)
    assert sum(abs(v) for v in adjusted.values()) == pytest.approx(0.30)
    assert "overlay_budget_cap" in state["active_circuit_breakers"]


def test_constructor_preserves_sum_and_constraints() -> None:
    core = {"SPY": 0.20, "QQQ": 0.15, "TLT": 0.15, "IEF": 0.10, "GLD": 0.10, "DBC": 0.10, "VNQ": 0.10, "VXUS": 0.10}
    tilts = {"SPY": -0.05, "TLT": 0.05}
    final_weights = apply_overlay(core, tilts)
    assert sum(final_weights.values()) == pytest.approx(1.0)
    assert min(final_weights.values()) >= 0.01 - 1e-9
    assert max(final_weights.values()) <= 0.25 + 1e-9


def test_constructor_repairs_invalid_naive_weights() -> None:
    core = {"SPY": 0.24, "QQQ": 0.24, "TLT": 0.14, "IEF": 0.10, "GLD": 0.08, "DBC": 0.08, "VNQ": 0.06, "VXUS": 0.06}
    tilts = {"SPY": 0.20, "QQQ": 0.10, "TLT": -0.15}
    final_weights = apply_overlay(core, tilts)
    assert sum(final_weights.values()) == pytest.approx(1.0)
    assert final_weights["SPY"] <= 0.25
    assert all(weight >= 0.01 for weight in final_weights.values())


def test_overlay_pipeline_runs_clean(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    dates = pd.date_range("2026-01-01", periods=110, freq="D")
    df = pd.DataFrame(
        {
            "date": list(dates.date) * 3,
            "signal_name": (["recession_prob"] * 110) + (["fed_cuts_expected"] * 110) + (["sp500_close_expected"] * 110),
            "value": ([0.10] * 100 + [0.28] * 10) + ([2.0] * 110) + ([5600.0] * 110),
            "source": ["polymarket"] * 330,
            "confidence": [1.0] * 330,
        }
    )
    vix = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=110, freq="D").date,
            "value": [18.0] * 100 + [30.0] * 10,
        }
    )

    monkeypatch.setattr(
        "app.robo_advisor.overlay.signal_builder._load_signal_history",
        lambda as_of_date: df[df["date"] <= as_of_date].copy(),
    )
    monkeypatch.setattr(
        "app.robo_advisor.overlay.signal_builder.MacroLoader.load",
        lambda self, series_id: vix.copy(),
    )
    monkeypatch.setattr(
        "app.robo_advisor.overlay.signal_builder.MacroLoader.__init__",
        lambda self, path=None, api_key=None: setattr(self, "path", tmp_path / "macro.csv"),
    )
    (tmp_path / "macro.csv").write_text("stub\n")

    core = {"SPY": 0.18, "QQQ": 0.16, "TLT": 0.15, "IEF": 0.12, "GLD": 0.10, "DBC": 0.09, "VNQ": 0.10, "VXUS": 0.10}
    preview = build_overlay_preview(date(2026, 4, 20), core)

    assert set(preview.final_weights) == set(core)
    assert sum(preview.final_weights.values()) == pytest.approx(1.0)
    assert preview.overlay_budget_used <= preview.overlay_budget_limit + 1e-9
