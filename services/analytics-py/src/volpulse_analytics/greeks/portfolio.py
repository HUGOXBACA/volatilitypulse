"""Aggregation of position-level Greeks into portfolio risk.

The aggregation is vectorised over the whole book: a desk with a few
thousand open positions must be able to revalue them on every snapshot
without a Python loop over the positions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from volpulse_analytics.pricing.black_scholes import black_scholes_greeks

__all__ = ["PortfolioRisk", "aggregate_portfolio_risk"]


@dataclass(frozen=True, slots=True)
class PortfolioRisk:
    """Aggregate risk of a book of option positions."""

    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    gross_notional: float
    net_notional: float
    position_count: int

    def as_dict(self) -> dict[str, float]:
        """Return the risk as a flat mapping, ready for persistence."""
        return {
            "delta": self.delta,
            "gamma": self.gamma,
            "vega": self.vega,
            "theta": self.theta,
            "rho": self.rho,
            "gross_notional": self.gross_notional,
            "net_notional": self.net_notional,
            "position_count": float(self.position_count),
        }


def aggregate_portfolio_risk(
    spot: ArrayLike,
    strike: ArrayLike,
    time_to_expiry: ArrayLike,
    rate: ArrayLike,
    dividend_yield: ArrayLike,
    volatility: ArrayLike,
    quantity: ArrayLike,
    *,
    is_call: ArrayLike | bool = True,
    contract_multiplier: float = 1.0,
) -> PortfolioRisk:
    """Aggregate the Greeks of a book of option positions.

    Args:
        spot: Underlying price for each position.
        strike: Strike of each position.
        time_to_expiry: Time to expiry of each position, in years.
        rate: Continuously compounded risk-free rate.
        dividend_yield: Continuously compounded dividend yield.
        volatility: Implied volatility of each position.
        quantity: Signed position size: negative is short.
        is_call: Whether each position is a call. A scalar applies to all.
        contract_multiplier: Multiplier applied to every price and Greek.

    Returns:
        The aggregated portfolio risk.
    """
    quantities = np.asarray(quantity, dtype=np.float64)
    if quantities.size == 0:
        return PortfolioRisk(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)

    calls = np.asarray(is_call, dtype=bool)
    if calls.ndim == 0:
        calls = np.full(quantities.shape, bool(calls))

    greeks = black_scholes_greeks(
        spot,
        strike,
        time_to_expiry,
        rate,
        dividend_yield,
        volatility,
        is_call=True,
    )

    # A short put has the opposite Greeks of a long put; the caller passes
    # signed quantities, so the sign of the position is applied once here.
    direction = np.where(calls, 1.0, -1.0)

    def weighted(name: str) -> float:
        per_position = greeks[name] * direction * quantities * contract_multiplier
        return float(np.sum(per_position))

    mids = np.asarray(spot, dtype=np.float64) * direction * quantities * contract_multiplier
    gross = float(np.sum(np.abs(mids)))
    net = float(np.sum(mids))

    return PortfolioRisk(
        delta=weighted("delta"),
        gamma=weighted("gamma"),
        vega=weighted("vega"),
        theta=weighted("theta"),
        rho=weighted("rho"),
        gross_notional=gross,
        net_notional=net,
        position_count=int(quantities.size),
    )
