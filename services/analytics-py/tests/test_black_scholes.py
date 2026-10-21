"""Tests for the Black-Scholes pricing and Greek engine."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from volpulse_analytics.pricing.black_scholes import (
    black_scholes_greeks,
    black_scholes_price,
    implied_volatility_from_price,
)


@given(
    spot=st.floats(min_value=1.0, max_value=1000.0),
    strike=st.floats(min_value=1.0, max_value=1000.0),
    maturity=st.floats(min_value=0.01, max_value=5.0),
    rate=st.floats(min_value=-0.05, max_value=0.15),
    dividend=st.floats(min_value=0.0, max_value=0.10),
    volatility=st.floats(min_value=0.05, max_value=2.0),
)
@settings(max_examples=200, deadline=None)
def test_put_call_parity(
    spot: float,
    strike: float,
    maturity: float,
    rate: float,
    dividend: float,
    volatility: float,
) -> None:
    """The call price minus the put price must equal the forward carry."""
    call = float(black_scholes_price(spot, strike, maturity, rate, dividend, volatility, is_call=True))
    put = float(black_scholes_price(spot, strike, maturity, rate, dividend, volatility, is_call=False))

    expected = spot * np.exp(-dividend * maturity) - strike * np.exp(-rate * maturity)
    assert call - put == pytest.approx(expected, rel=1e-8, abs=1e-8)


@given(
    spot=st.floats(min_value=1.0, max_value=1000.0),
    strike=st.floats(min_value=1.0, max_value=1000.0),
    maturity=st.floats(min_value=0.05, max_value=5.0),
    rate=st.floats(min_value=-0.05, max_value=0.15),
    dividend=st.floats(min_value=0.0, max_value=0.10),
    volatility=st.floats(min_value=0.05, max_value=2.0),
)
@settings(max_examples=200, deadline=None)
def test_price_is_within_the_no_arbitrage_bounds(
    spot: float,
    strike: float,
    maturity: float,
    rate: float,
    dividend: float,
    volatility: float,
) -> None:
    """A European option can never trade outside its bounds."""
    price = float(black_scholes_price(spot, strike, maturity, rate, dividend, volatility))
    lower = max(spot * np.exp(-dividend * maturity) - strike * np.exp(-rate * maturity), 0.0)
    upper = spot * np.exp(-dividend * maturity)
    assert lower - 1e-9 <= price <= upper + 1e-9


@given(
    spot=st.floats(min_value=10.0, max_value=500.0),
    moneyness=st.floats(min_value=0.8, max_value=1.25),
    maturity=st.floats(min_value=0.25, max_value=5.0),
    rate=st.floats(min_value=-0.05, max_value=0.15),
    dividend=st.floats(min_value=0.0, max_value=0.10),
    volatility=st.floats(min_value=0.10, max_value=2.0),
)
@settings(max_examples=200, deadline=None)
def test_implied_volatility_round_trip(
    spot: float,
    moneyness: float,
    maturity: float,
    rate: float,
    dividend: float,
    volatility: float,
) -> None:
    """Inverting the price must recover the volatility that produced it.

    The strategy keeps the option inside a range where the volatility is
    identifiable: a contract that is worthless, or worth exactly its
    intrinsic value, has no implied volatility to recover.
    """
    strike = spot * moneyness
    price = black_scholes_price(spot, strike, maturity, rate, dividend, volatility)
    recovered = implied_volatility_from_price(price, spot, strike, maturity, rate, dividend)
    assert float(recovered) == pytest.approx(volatility, rel=1e-4)


def test_vectorised_solver_matches_scalar_solver() -> None:
    """A batch must give the same answers as the element-wise solver."""
    strikes = np.array([80.0, 90.0, 100.0, 110.0, 120.0])
    price = black_scholes_price(100.0, strikes, 0.5, 0.03, 0.01, 0.25)

    batch = implied_volatility_from_price(price, 100.0, strikes, 0.5, 0.03, 0.01)

    for index, strike in enumerate(strikes):
        single = implied_volatility_from_price(
            float(price[index]), 100.0, float(strike), 0.5, 0.03, 0.01
        )
        assert float(batch[index]) == pytest.approx(float(single), rel=1e-9)


def test_impossible_prices_return_nan() -> None:
    """A price outside the no-arbitrage bounds has no implied volatility."""
    result = implied_volatility_from_price(1e6, 100.0, 100.0, 1.0, 0.03, 0.0)
    assert np.isnan(float(result))


def test_expired_option_is_worth_its_intrinsic_value() -> None:
    """At expiry the option is a simple intrinsic value payoff."""
    assert float(black_scholes_price(120.0, 100.0, 0.0, 0.03, 0.0, 0.25)) == pytest.approx(20.0)
    assert float(black_scholes_price(80.0, 100.0, 0.0, 0.03, 0.0, 0.25, is_call=False)) == pytest.approx(20.0)


def test_call_delta_is_bounded() -> None:
    """A call delta lies between zero and the discounted spot."""
    greeks = black_scholes_greeks(100.0, np.array([80.0, 100.0, 120.0]), 0.5, 0.03, 0.01, 0.25)
    assert np.all(greeks["delta"] >= 0.0)
    assert np.all(greeks["delta"] <= np.exp(-0.01 * 0.5) + 1e-12)


def test_gamma_is_positive_and_peaks_at_the_forward() -> None:
    """Gamma is largest at the forward strike and never negative."""
    strikes = np.linspace(70.0, 130.0, 601)
    rate = 0.03
    dividend = 0.01
    maturity = 0.5
    greeks = black_scholes_greeks(100.0, strikes, maturity, rate, dividend, 0.25)
    gamma = greeks["gamma"]

    assert np.all(gamma > 0.0)

    forward = 100.0 * np.exp((rate - dividend) * maturity)
    peak_strike = strikes[int(np.argmax(gamma))]
    assert peak_strike == pytest.approx(forward, rel=0.02)


def test_vega_vanishes_at_expiry() -> None:
    """A contract that has expired has no volatility sensitivity."""
    greeks = black_scholes_greeks(100.0, 100.0, 0.0, 0.03, 0.0, 0.25)
    assert float(greeks["vega"]) == pytest.approx(0.0)
    assert float(greeks["gamma"]) == pytest.approx(0.0)
