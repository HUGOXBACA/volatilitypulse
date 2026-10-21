"""Portfolio risk.

The Greeks are computed analytically in
:mod:`volpulse_analytics.pricing.black_scholes`; this package aggregates them
over a portfolio and expresses the result in the units the desk uses.
"""

from __future__ import annotations

from volpulse_analytics.greeks.portfolio import aggregate_portfolio_risk

__all__ = ["aggregate_portfolio_risk"]
