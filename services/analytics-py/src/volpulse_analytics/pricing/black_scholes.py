"""Black-Scholes-Merton pricing and analytic Greeks.

Everything in this module is vectorised over NumPy arrays: the analytics
engine evaluates thousands of contracts per snapshot, and a Python-level loop
over them would dominate the latency budget.

Conventions
-----------
* ``time_to_expiry`` is expressed in **years** (ACT/365).
* ``rate`` and ``dividend_yield`` are continuously compounded.
* ``volatility`` is a decimal (0.25 means 25%).
* Prices are per unit of the underlying; multiply by the contract
  multiplier at the portfolio layer.
"""

from __future__ import annotations

from typing import cast

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.special import ndtr

__all__ = [
    "black_scholes_greeks",
    "black_scholes_price",
    "implied_volatility_from_price",
]

_VOL_FLOOR = 1e-6
_VOL_CAP = 5.0


def _norm_cdf(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """Standard normal cumulative distribution function.

    ``scipy.special.ndtr`` is used rather than an ``erf`` based
    implementation: it is both faster and accurate in the far tails, which
    is where deep out-of-the-money quotes live.
    """
    # ndtr is typed as returning Any; the cast documents the real type.
    return cast(NDArray[np.float64], np.asarray(ndtr(x), dtype=np.float64))


def _norm_pdf(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """Standard normal probability density function."""
    density = np.exp(-0.5 * x * x) / np.sqrt(2.0 * np.pi)
    return cast(NDArray[np.float64], np.asarray(density, dtype=np.float64))


def _as_array(value: ArrayLike) -> NDArray[np.float64]:
    """Convert to a float64 array, broadcasting against the other inputs."""
    return np.asarray(value, dtype=np.float64)


def black_scholes_price(
    spot: ArrayLike,
    strike: ArrayLike,
    time_to_expiry: ArrayLike,
    rate: ArrayLike,
    dividend_yield: ArrayLike,
    volatility: ArrayLike,
    *,
    is_call: bool = True,
) -> NDArray[np.float64]:
    """Price a European option.

    Args:
        spot: Current price of the underlying.
        strike: Strike price.
        time_to_expiry: Time to expiry in years.
        rate: Continuously compounded risk-free rate.
        dividend_yield: Continuously compounded dividend yield.
        volatility: Implied volatility, as a decimal.
        is_call: Price a call when true, a put otherwise.

    Returns:
        The option price, with the shape of the broadcast inputs.
    """
    s = _as_array(spot)
    k = _as_array(strike)
    t = _as_array(time_to_expiry)
    r = _as_array(rate)
    q = _as_array(dividend_yield)
    sigma = _as_array(volatility)

    with np.errstate(divide="ignore", invalid="ignore"):
        sqrt_t = np.sqrt(np.maximum(t, 0.0))
        safe_sigma = np.maximum(sigma, _VOL_FLOOR)

        d1 = (np.log(s / k) + (r - q + 0.5 * safe_sigma**2) * t) / (safe_sigma * sqrt_t)
        d2 = d1 - safe_sigma * sqrt_t

        discount_r = np.exp(-r * t)
        discount_q = np.exp(-q * t)

        call = s * discount_q * _norm_cdf(d1) - k * discount_r * _norm_cdf(d2)
        put = k * discount_r * _norm_cdf(-d2) - s * discount_q * _norm_cdf(-d1)

        price = call if is_call else put

        # At (or past) expiry the option is worth its intrinsic value.
        expired = t <= 0.0
        intrinsic = np.maximum(s - k, 0.0) if is_call else np.maximum(k - s, 0.0)
        price = np.where(expired, intrinsic, price)

    return np.asarray(price, dtype=np.float64)


def black_scholes_greeks(
    spot: ArrayLike,
    strike: ArrayLike,
    time_to_expiry: ArrayLike,
    rate: ArrayLike,
    dividend_yield: ArrayLike,
    volatility: ArrayLike,
    *,
    is_call: bool = True,
) -> dict[str, NDArray[np.float64]]:
    """Analytic Greeks of a European option.

    Returns:
        A mapping with ``delta``, ``gamma``, ``vega``, ``theta`` and ``rho``.
        ``vega`` is per 1.00 of volatility (not per 1%), ``theta`` is per
        calendar day, and ``rho`` is per 1.00 of rate.
    """
    s = _as_array(spot)
    k = _as_array(strike)
    t = _as_array(time_to_expiry)
    r = _as_array(rate)
    q = _as_array(dividend_yield)
    sigma = _as_array(volatility)

    with np.errstate(divide="ignore", invalid="ignore"):
        sqrt_t = np.sqrt(np.maximum(t, 0.0))
        safe_sigma = np.maximum(sigma, _VOL_FLOOR)

        d1 = (np.log(s / k) + (r - q + 0.5 * safe_sigma**2) * t) / (safe_sigma * sqrt_t)
        d2 = d1 - safe_sigma * sqrt_t

        pdf_d1 = _norm_pdf(d1)
        discount_r = np.exp(-r * t)
        discount_q = np.exp(-q * t)

        delta = discount_q * _norm_cdf(d1)
        if not is_call:
            delta = delta - discount_q

        gamma = discount_q * pdf_d1 / (s * safe_sigma * sqrt_t)
        vega = s * discount_q * pdf_d1 * sqrt_t
        rho = (
            k * t * discount_r * _norm_cdf(d2) if is_call else -k * t * discount_r * _norm_cdf(-d2)
        )

        theta_common = -(s * pdf_d1 * safe_sigma * discount_q) / (2.0 * sqrt_t)
        theta = (
            theta_common - r * k * discount_r * _norm_cdf(d2) + q * s * discount_q * _norm_cdf(d1)
            if is_call
            else theta_common
            + r * k * discount_r * _norm_cdf(-d2)
            - q * s * discount_q * _norm_cdf(-d1)
        )
        # Annual theta is quoted per calendar day.
        theta = theta / 365.0

        # At expiry the sensitivities collapse to their piecewise constants.
        expired = t <= 0.0
        delta = np.where(
            expired,
            np.where(is_call, (s > k).astype(np.float64), (s < k).astype(np.float64) * -1.0),
            delta,
        )
        gamma = np.where(expired, 0.0, gamma)
        vega = np.where(expired, 0.0, vega)
        theta = np.where(expired, 0.0, theta)
        rho = np.where(expired, 0.0, rho)

    return {
        "delta": np.asarray(delta, dtype=np.float64),
        "gamma": np.asarray(gamma, dtype=np.float64),
        "vega": np.asarray(vega, dtype=np.float64),
        "theta": np.asarray(theta, dtype=np.float64),
        "rho": np.asarray(rho, dtype=np.float64),
    }


def implied_volatility_from_price(
    market_price: ArrayLike,
    spot: ArrayLike,
    strike: ArrayLike,
    time_to_expiry: ArrayLike,
    rate: ArrayLike,
    dividend_yield: ArrayLike,
    *,
    is_call: bool = True,
    tolerance: float = 1e-8,
    max_iterations: int = 100,
) -> NDArray[np.float64]:
    """Solve for the implied volatility that reproduces ``market_price``.

    The solver is a vectorised bisection: it cannot diverge, unlike a pure
    Newton iteration, and bisection on a monotone price function converges
    linearly but predictably. Every element of the input is solved
    independently, so one bad option never stalls the batch.

    Args:
        market_price: Observed option price.
        spot: Current price of the underlying.
        strike: Strike price.
        time_to_expiry: Time to expiry in years.
        rate: Continuously compounded risk-free rate.
        dividend_yield: Continuously compounded dividend yield.
        is_call: Solve for a call when true, a put otherwise.
        tolerance: Absolute tolerance on the implied volatility.
        max_iterations: Maximum bisection iterations.

    Returns:
        The implied volatility per element. Elements whose market price is
        outside the no-arbitrage bounds return ``nan``.
    """
    price = _as_array(market_price)
    s = _as_array(spot)
    k = _as_array(strike)
    t = _as_array(time_to_expiry)
    r = _as_array(rate)
    q = _as_array(dividend_yield)

    with np.errstate(divide="ignore", invalid="ignore"):
        discount_r = np.exp(-r * t)
        discount_q = np.exp(-q * t)

        lower_bound = np.maximum(
            s * discount_q - k * discount_r if is_call else k * discount_r - s * discount_q,
            0.0,
        )
        upper_bound = s * discount_q if is_call else k * discount_r

        solvable = np.isfinite(price) & (t > 0.0) & (price > lower_bound) & (price < upper_bound)

        low = np.full(np.broadcast(price, s, k, t, r, q).shape, _VOL_FLOOR, dtype=np.float64)
        high = np.full(low.shape, _VOL_CAP, dtype=np.float64)

        for _ in range(max_iterations):
            mid = 0.5 * (low + high)
            mid_price = black_scholes_price(s, k, t, r, q, mid, is_call=is_call)
            too_low = mid_price < price
            low = np.where(too_low, mid, low)
            high = np.where(too_low, high, mid)
            if np.all(np.abs(high - low) < tolerance):
                break

        result = 0.5 * (low + high)
        return np.where(solvable, result, np.nan)
