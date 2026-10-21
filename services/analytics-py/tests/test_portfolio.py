"""Tests for the portfolio risk aggregation."""

from __future__ import annotations

import numpy as np
import pytest

from volpulse_analytics.greeks.portfolio import aggregate_portfolio_risk


def test_empty_portfolio_has_no_risk() -> None:
    """An empty book aggregates to zero."""
    risk = aggregate_portfolio_risk(
        spot=[], strike=[], time_to_expiry=[], rate=[], dividend_yield=[], volatility=[], quantity=[]
    )
    assert risk.position_count == 0
    assert risk.delta == 0.0
    assert risk.gross_notional == 0.0


def test_long_and_short_positions_cancel() -> None:
    """A hedged book has no net delta."""
    risk = aggregate_portfolio_risk(
        spot=[100.0, 100.0],
        strike=[100.0, 100.0],
        time_to_expiry=[0.5, 0.5],
        rate=[0.03, 0.03],
        dividend_yield=[0.0, 0.0],
        volatility=[0.25, 0.25],
        quantity=[10.0, -10.0],
    )
    assert risk.delta == pytest.approx(0.0, abs=1e-9)
    assert risk.gamma == pytest.approx(0.0, abs=1e-9)
    assert risk.net_notional == pytest.approx(0.0, abs=1e-9)
    assert risk.gross_notional == pytest.approx(2000.0)


def test_put_delta_is_negative() -> None:
    """A long put is short the underlying."""
    call = aggregate_portfolio_risk(
        spot=[100.0],
        strike=[100.0],
        time_to_expiry=[0.5],
        rate=[0.03],
        dividend_yield=[0.0],
        volatility=[0.25],
        quantity=[1.0],
        is_call=True,
    )
    put = aggregate_portfolio_risk(
        spot=[100.0],
        strike=[100.0],
        time_to_expiry=[0.5],
        rate=[0.03],
        dividend_yield=[0.0],
        volatility=[0.25],
        quantity=[1.0],
        is_call=False,
    )

    assert call.delta > 0.0
    assert put.delta < 0.0
    assert call.delta + put.delta == pytest.approx(0.0, abs=1e-9)


def test_contract_multiplier_scales_the_risk() -> None:
    """The contract multiplier must scale every risk number."""
    single = aggregate_portfolio_risk(
        spot=[100.0],
        strike=[100.0],
        time_to_expiry=[0.5],
        rate=[0.03],
        dividend_yield=[0.0],
        volatility=[0.25],
        quantity=[1.0],
        contract_multiplier=1.0,
    )
    multiplied = aggregate_portfolio_risk(
        spot=[100.0],
        strike=[100.0],
        time_to_expiry=[0.5],
        rate=[0.03],
        dividend_yield=[0.0],
        volatility=[0.25],
        quantity=[1.0],
        contract_multiplier=100.0,
    )

    assert multiplied.delta == pytest.approx(single.delta * 100.0)
    assert multiplied.gamma == pytest.approx(single.gamma * 100.0)


def test_as_dict_is_flat() -> None:
    """The risk must serialise into a flat mapping."""
    risk = aggregate_portfolio_risk(
        spot=[100.0],
        strike=[100.0],
        time_to_expiry=[0.5],
        rate=[0.03],
        dividend_yield=[0.0],
        volatility=[0.25],
        quantity=[1.0],
    )
    payload = risk.as_dict()
    assert set(payload) == {
        "delta",
        "gamma",
        "vega",
        "theta",
        "rho",
        "gross_notional",
        "net_notional",
        "position_count",
    }
    assert all(isinstance(value, float) for value in payload.values())


def test_aggregation_is_vectorised_over_mixed_positions() -> None:
    """Mixed books aggregate in one pass."""
    risk = aggregate_portfolio_risk(
        spot=np.array([100.0, 100.0, 100.0]),
        strike=np.array([90.0, 100.0, 110.0]),
        time_to_expiry=np.array([0.25, 0.5, 1.0]),
        rate=np.array([0.03, 0.03, 0.03]),
        dividend_yield=np.array([0.0, 0.0, 0.0]),
        volatility=np.array([0.22, 0.25, 0.28]),
        quantity=np.array([5.0, -3.0, 2.0]),
        is_call=np.array([True, True, False]),
    )
    assert risk.position_count == 3
    assert np.isfinite(risk.delta)
    assert np.isfinite(risk.vega)
