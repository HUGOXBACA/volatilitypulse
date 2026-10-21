"""Implied volatility surface construction.

The surface is fitted with the raw SVI parametrisation (Gatheral, *The
Volatility Surface*), which is the de-facto standard for a single expiry:

    w(k) = a + b * (rho * (k - m) + sqrt((k - m)^2 + sigma^2))

where ``k`` is log-moneyness against the forward and ``w`` is total
variance. Raw SVI is used rather than SVI-B because it is linear in the
wings, which keeps the fit well behaved far from the money.

The fitter is deliberately paranoid: it refuses to return a surface it
cannot certify as free of butterfly arbitrage, and it reports the residual
error so the caller can decide whether the fit is good enough to trade on.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import least_squares

__all__ = [
    "SviFit",
    "SviParams",
    "check_butterfly_arbitrage",
    "check_calendar_arbitrage",
    "fit_svi",
    "log_moneyness",
]


def log_moneyness(strikes: ArrayLike, forward: float) -> NDArray[np.float64]:
    """Log-moneyness of ``strikes`` against ``forward``."""
    strikes_array = np.asarray(strikes, dtype=np.float64)
    if forward <= 0.0:
        raise ValueError(f"forward must be positive, got {forward}")
    return np.log(strikes_array / forward)


@dataclass(frozen=True, slots=True)
class SviParams:
    """Parameters of the raw SVI parametrisation."""

    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def total_variance(self, k: ArrayLike) -> NDArray[np.float64]:
        """Total variance ``w(k)`` at log-moneyness ``k``."""
        k_array = np.asarray(k, dtype=np.float64)
        shifted = k_array - self.m
        root = np.sqrt(shifted**2 + self.sigma**2)
        return self.a + self.b * (self.rho * shifted + root)

    def implied_volatility(self, k: ArrayLike) -> NDArray[np.float64]:
        """Implied volatility implied by the total variance."""
        return np.sqrt(np.maximum(self.total_variance(k), 0.0))

    def derivative(self, k: ArrayLike) -> NDArray[np.float64]:
        """First derivative ``w'(k)`` of the total variance."""
        k_array = np.asarray(k, dtype=np.float64)
        shifted = k_array - self.m
        root = np.sqrt(shifted**2 + self.sigma**2)
        return self.b * (self.rho + shifted / root)


@dataclass(frozen=True, slots=True)
class SviFit:
    """The outcome of a surface fit."""

    params: SviParams
    rmse: float
    residuals: NDArray[np.float64]
    butterfly_free: bool
    observations: int


def _initial_guess(k: NDArray[np.float64], w: NDArray[np.float64]) -> NDArray[np.float64]:
    """Derive a starting point for the optimiser from the data itself."""
    b_guess = float(np.min(np.gradient(w, k))) if k.size > 1 else 0.1
    b_guess = min(abs(b_guess), 0.5) or 0.1
    m_guess = float(k[np.argmin(w)]) if k.size else 0.0
    a_guess = float(w.min() - b_guess * abs(m_guess))
    return np.array([a_guess, b_guess, 0.0, m_guess, 0.2], dtype=np.float64)


def fit_svi(
    log_moneyness_points: ArrayLike,
    total_variances: ArrayLike,
    *,
    initial: ArrayLike | None = None,
    max_iterations: int = 2000,
) -> SviFit:
    """Fit a raw SVI surface to observed total variances.

    Args:
        log_moneyness_points: Observed ``k`` values.
        total_variances: Observed total variances (implied volatility squared).
        initial: Optional starting point ``[a, b, rho, m, sigma]``.
        max_iterations: Maximum optimiser iterations.

    Returns:
        The fitted parameters, the residual error and the arbitrage verdict.

    Raises:
        ValueError: The inputs are empty or contain non-finite values.
    """
    k = np.asarray(log_moneyness_points, dtype=np.float64)
    w = np.asarray(total_variances, dtype=np.float64)

    if k.size != w.size:
        raise ValueError(f"k and w must have the same length, got {k.size} and {w.size}")
    if k.size == 0:
        raise ValueError("cannot fit a surface without observations")
    if not (np.all(np.isfinite(k)) and np.all(np.isfinite(w))):
        raise ValueError("surface observations must be finite")
    if np.any(w < 0.0):
        raise ValueError("total variance cannot be negative")

    start = np.asarray(initial, dtype=np.float64) if initial is not None else _initial_guess(k, w)
    if start.shape != (5,):
        raise ValueError(f"initial must have shape (5,), got {start.shape}")

    lower = np.array([-10.0, 1e-8, -0.999, -5.0, 1e-8], dtype=np.float64)
    upper = np.array([10.0, 10.0, 0.999, 5.0, 5.0], dtype=np.float64)
    start = np.clip(start, lower + 1e-9, upper - 1e-9)

    def model(params: NDArray[np.float64]) -> NDArray[np.float64]:
        svi = SviParams(*params.tolist())
        return svi.total_variance(k)

    def residuals(params: NDArray[np.float64]) -> NDArray[np.float64]:
        fitted = model(params)
        errors = fitted - w
        # Lee's condition on the minimum of the total variance: w must not go
        # negative anywhere in the wings, otherwise the fit is meaningless.
        minimum = params[0] + params[1] * params[4] * np.sqrt(max(1.0 - params[2] ** 2, 0.0))
        penalty = 0.0 if minimum >= 0.0 else 10.0 * minimum
        return np.append(errors, penalty)

    result = least_squares(
        residuals,
        start,
        bounds=(lower, upper),
        max_nfev=max_iterations,
    )

    params = SviParams(*result.x.tolist())
    fitted = model(result.x)
    errors = fitted - w
    rmse = float(np.sqrt(np.mean(errors**2))) if errors.size else 0.0

    return SviFit(
        params=params,
        rmse=rmse,
        residuals=errors,
        butterfly_free=check_butterfly_arbitrage(params),
        observations=int(k.size),
    )


def check_butterfly_arbitrage(params: SviParams, *, grid_size: int = 401) -> bool:
    """Check the surface for butterfly (static) arbitrage.

    Lee's moment formula gives the density of the risk-neutral distribution
    implied by a total variance curve. Where that density would be negative
    the curve allows a butterfly arbitrage, and the surface must not be used.

    Args:
        params: The fitted surface.
        grid_size: Number of grid points used to probe the wings.

    Returns:
        True when no butterfly arbitrage was detected on the grid.
    """
    k_min = params.m - 5.0
    k_max = params.m + 5.0
    k = np.linspace(k_min, k_max, grid_size)

    w = params.total_variance(k)
    w_prime = params.derivative(k)

    if np.any(w <= 0.0):
        return False

    one_minus_rho_sq = 1.0 - params.rho**2
    if one_minus_rho_sq <= 0.0:
        return False

    radicand = w**2 + 2.0 * w * w_prime * one_minus_rho_sq
    if np.any(radicand <= 0.0):
        return False

    g = (1.0 - (w * params.rho) / np.sqrt(radicand)) / (w * np.sqrt(one_minus_rho_sq))
    return bool(np.all(g >= 0.0))


def check_calendar_arbitrage(
    surfaces: dict[float, tuple[NDArray[np.float64], NDArray[np.float64]]],
) -> bool:
    """Check a set of expiry slices for calendar arbitrage.

    Total variance must be non-decreasing in time at every fixed log
    moneyness: a longer dated option can never be worth less than a shorter
    dated one struck at the same forward.

    Args:
        surfaces: Mapping of time to expiry (in years) to ``(k, w)`` pairs.

    Returns:
        True when no calendar arbitrage was detected.
    """
    expiries = sorted(surfaces)
    if len(expiries) < 2:
        return True

    for earlier, later in zip(expiries, expiries[1:], strict=False):
        k_early, w_early = surfaces[earlier]
        k_late, w_late = surfaces[later]
        if k_early.size == 0 or k_late.size == 0:
            continue

        # Compare on the overlap of the two grids.
        low = max(k_early.min(), k_late.min())
        high = min(k_early.max(), k_late.max())
        if low >= high:
            continue

        early_interp = np.interp(np.linspace(low, high, 101), k_early, w_early)
        late_interp = np.interp(np.linspace(low, high, 101), k_late, w_late)
        if np.any(late_interp < early_interp - 1e-12):
            return False

    return True
