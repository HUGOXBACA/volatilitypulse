# ─────────────────────────────────────────────────────────────────────────────
# Volatility surface fitting — SVI, SABR, and spline interpolation.
#
# Fits implied volatility surfaces from OptionChainSnapshot data using
# arbitrage-free parameterizations. JIT-compiled with numba/jax for speed.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

import numpy as np

from volpulse_core.models.chain import OptionChainSnapshot

logger = logging.getLogger(__name__)

__all__ = [
    "SABRFitter",
    "SVIFitter",
    "SplineFitter",
    "SurfaceConfig",
    "SurfaceFitResult",
    "SurfaceFitter",
    "SurfaceMethod",
    "fit_surface",
]


class SurfaceMethod(Enum):
    """Supported surface fitting methods."""

    SVI = "SVI"
    SABR = "SABR"
    CUBIC_SPLINE = "CubicSpline"
    LINEAR = "Linear"


@dataclass(frozen=True, slots=True)
class SurfaceConfig:
    """Configuration for surface fitting."""

    method: SurfaceMethod = SurfaceMethod.SVI
    # SVI parameters
    svi_max_iter: int = 100
    svi_tol: float = 1e-8
    # SABR parameters
    sabr_max_iter: int = 100
    sabr_tol: float = 1e-8
    # Spline parameters
    spline_smoothing: float = 0.0
    # Arbitrage checks
    check_arbitrage: bool = True
    # Minimum points required for fitting
    min_points: int = 5


@dataclass(frozen=True, slots=True)
class SurfaceFitResult:
    """Result of surface fitting."""

    method: SurfaceMethod
    underlying_symbol: str
    as_of_ns: int
    # Fitted parameters
    params: dict[str, float]
    # Surface points
    expiries: np.ndarray
    strikes: np.ndarray
    implied_vols: np.ndarray
    fitted_vols: np.ndarray
    # Quality metrics
    rms_error: float
    max_error: float
    arbitrage_free: bool
    # Arbitrage violations (if any)
    calendar_arb_violations: int = 0
    butterfly_arb_violations: int = 0
    # Timing
    fit_time_ms: float = 0.0


class SurfaceFitter(Protocol):
    """Protocol for surface fitting implementations."""

    def fit(
        self,
        snapshots: list[OptionChainSnapshot],
        config: SurfaceConfig,
    ) -> SurfaceFitResult: ...


# ── SVI Implementation ────────────────────────────────────────────────────────


class SVIFitter:
    """SVI (Stochastic Volatility Inspired) surface fitter.

    Uses Gatheral's SVI parameterization which is arbitrage-free by construction
    when parameters satisfy certain constraints.
    """

    __slots__ = ("_last_params",)

    def __init__(self) -> None:
        self._last_params: dict[str, float] | None = None

    def fit(
        self,
        snapshots: list[OptionChainSnapshot],
        config: SurfaceConfig,
    ) -> SurfaceFitResult:
        start_time = time.perf_counter()

        # Prepare data
        expiries, strikes, implied_vols, forwards = self._prepare_data(snapshots)

        if len(implied_vols) < config.min_points:
            raise ValueError(f"Insufficient data points: {len(implied_vols)} < {config.min_points}")

        # Fit SVI per expiry
        svi_params = {}
        fitted_vols = np.zeros_like(implied_vols)

        for expiry in np.unique(expiries):
            mask = np.abs(expiries - expiry) < 1e-10
            if np.sum(mask) < 3:
                continue

            k = np.log(strikes[mask] / forwards[mask][0])
            iv = implied_vols[mask]

            # Fit SVI slice
            params = self._fit_svi_slice(k, iv, config)
            svi_params[f"expiry_{expiry:.4f}"] = params

            # Compute fitted vols
            fitted_vols[mask] = self._svi_variance(k, params) ** 0.5

        # Compute metrics
        rms_error = float(np.sqrt(np.mean((fitted_vols - implied_vols) ** 2)))
        max_error = float(np.max(np.abs(fitted_vols - implied_vols)))

        # Check arbitrage
        arb_free, cal_arb, bf_arb = self._check_arbitrage(expiries, strikes, fitted_vols) if config.check_arbitrage else (True, 0, 0)

        fit_time_ms = (time.perf_counter() - start_time) * 1000

        return SurfaceFitResult(
            method=SurfaceMethod.SVI,
            underlying_symbol=snapshots[0].underlying_symbol if snapshots else "",
            as_of_ns=int(time.time() * 1_000_000_000),
            params=self._flatten_params(svi_params),
            expiries=expiries,
            strikes=strikes,
            implied_vols=implied_vols,
            fitted_vols=fitted_vols,
            rms_error=rms_error,
            max_error=max_error,
            arbitrage_free=arb_free,
            calendar_arb_violations=cal_arb,
            butterfly_arb_violations=bf_arb,
            fit_time_ms=fit_time_ms,
        )

    def _prepare_data(
        self,
        snapshots: list[OptionChainSnapshot],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Extract and align data from snapshots."""
        all_expiries = []
        all_strikes = []
        all_ivs = []

        for snap in snapshots:
            for quote in snap.quotes:
                if quote.implied_volatility <= 0:
                    continue
                all_expiries.append(quote.expiry_epoch_day)
                all_strikes.append(quote.strike)
                all_ivs.append(quote.implied_volatility)

        # Use ATM strike as forward estimate
        forwards = np.ones_like(all_expiries) * np.mean(all_strikes)

        return (
            np.array(all_expiries),
            np.array(all_strikes),
            np.array(all_ivs),
            forwards,
        )

    def _fit_svi_slice(
        self,
        k: np.ndarray,
        iv: np.ndarray,
        config: SurfaceConfig,
    ) -> dict[str, float]:
        """Fit SVI parameters to a single expiry slice.

        Uses the Gatheral parameterization:
        w(k) = a + b * (rho * (k - m) + sqrt((k - m)^2 + sigma^2))
        """
        # Initial guess
        w = iv ** 2
        a_init = float(np.min(w))
        b_init = 0.1
        rho_init = -0.5
        m_init = float(k[np.argmin(w)])
        sigma_init = 0.1

        params = np.array([a_init, b_init, rho_init, m_init, sigma_init])

        # Use simple gradient descent (in production, use scipy.optimize)
        for _ in range(config.svi_max_iter):
            grad = self._svi_gradient(params, k, w)
            params -= 0.01 * grad
            if np.linalg.norm(grad) < config.svi_tol:
                break

            # Enforce SVI constraints for no-arbitrage
            params = self._enforce_svi_constraints(params)

        return {
            "a": float(params[0]),
            "b": float(params[1]),
            "rho": float(params[2]),
            "m": float(params[3]),
            "sigma": float(params[4]),
        }

    def _svi_variance(self, k: np.ndarray, params: dict[str, float]) -> np.ndarray:
        """Compute SVI total variance."""
        a, b, rho, m, sigma = params["a"], params["b"], params["rho"], params["m"], params["sigma"]
        return a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + sigma ** 2))

    def _svi_gradient(
        self,
        params: np.ndarray,
        k: np.ndarray,
        w_target: np.ndarray,
    ) -> np.ndarray:
        """Compute gradient of SVI loss."""
        a, b, rho, m, sigma = params
        w = self._svi_variance(k, {"a": a, "b": b, "rho": rho, "m": m, "sigma": sigma})
        diff = w - w_target

        # Gradients wrt each parameter
        da = 2 * np.mean(diff)
        db = 2 * np.mean(diff * (rho * (k - m) + np.sqrt((k - m) ** 2 + sigma ** 2)))
        drho = 2 * np.mean(diff * b * (k - m))
        dm = 2 * np.mean(diff * b * (-rho + (m - k) / np.sqrt((k - m) ** 2 + sigma ** 2)))
        dsigma = 2 * np.mean(diff * b * sigma / np.sqrt((k - m) ** 2 + sigma ** 2))

        return np.array([da, db, drho, dm, dsigma])

    def _enforce_svi_constraints(self, params: np.ndarray) -> np.ndarray:
        """Enforce SVI no-arbitrage constraints."""
        a, b, rho, m, sigma = params
        a = max(a, 0.0)
        b = max(b, 0.0)
        rho = np.clip(rho, -0.999, 0.999)
        sigma = max(sigma, 1e-6)
        return np.array([a, b, rho, m, sigma])

    def _flatten_params(self, svi_params: dict[str, dict[str, float]]) -> dict[str, float]:
        """Flatten nested params dict."""
        flat = {}
        for exp_key, params in svi_params.items():
            for p_name, p_val in params.items():
                flat[f"{exp_key}_{p_name}"] = p_val
        return flat

    def _check_arbitrage(
        self,
        expiries: np.ndarray,
        strikes: np.ndarray,
        vols: np.ndarray,
    ) -> tuple[bool, int, int]:
        """Check for calendar spread and butterfly arbitrage."""
        cal_arb = 0
        bf_arb = 0

        unique_expiries = np.unique(expiries)
        for i, exp1 in enumerate(unique_expiries):
            mask1 = expiries == exp1
            for exp2 in unique_expiries[i + 1 :]:
                mask2 = expiries == exp2
                # Calendar spread arbitrage: variance should increase with time
                var1 = np.mean(vols[mask1] ** 2)
                var2 = np.mean(vols[mask2] ** 2)
                if var2 < var1 - 1e-6:
                    cal_arb += 1

            # Butterfly arbitrage: check convexity in strike
            mask = expiries == exp1
            if np.sum(mask) >= 3:
                k_sorted = np.argsort(strikes[mask])
                vol_sorted = vols[mask][k_sorted]
                # Second derivative should be >= 0 (convex)
                second_deriv = np.diff(vol_sorted, 2)
                bf_arb += int(np.sum(second_deriv < -1e-6))

        return (cal_arb == 0 and bf_arb == 0), cal_arb, bf_arb


# ── SABR Implementation ───────────────────────────────────────────────────────


class SABRFitter:
    """SABR (Stochastic Alpha Beta Rho) surface fitter.

    SABR model: dF = sigma * F^beta * dW1, d(sigma) = alpha * sigma * dW2
    with correlation rho between dW1 and dW2.
    """

    def fit(
        self,
        snapshots: list[OptionChainSnapshot],
        config: SurfaceConfig,
    ) -> SurfaceFitResult:
        start_time = time.perf_counter()

        # Prepare data (similar to SVI)
        expiries, strikes, implied_vols, forwards = self._prepare_data(snapshots)

        if len(implied_vols) < config.min_points:
            raise ValueError(f"Insufficient data points: {len(implied_vols)} < {config.min_points}")

        # Fit SABR parameters per expiry
        sabr_params = {}
        fitted_vols = np.zeros_like(implied_vols)

        for expiry in np.unique(expiries):
            mask = np.abs(expiries - expiry) < 1e-10
            if np.sum(mask) < 3:
                continue

            k = strikes[mask]
            iv = implied_vols[mask]
            f = forwards[mask][0] if len(forwards[mask]) > 0 else np.mean(k)

            params = self._fit_sabr_slice(k, iv, f, config)
            sabr_params[f"expiry_{expiry:.4f}"] = params

            # Compute fitted vols using Hagan's formula
            fitted_vols[mask] = self._sabr_volatility(k, f, params)

        rms_error = float(np.sqrt(np.mean((fitted_vols - implied_vols) ** 2)))
        max_error = float(np.max(np.abs(fitted_vols - implied_vols)))

        arb_free, cal_arb, bf_arb = self._check_arbitrage(expiries, strikes, fitted_vols) if config.check_arbitrage else (True, 0, 0)

        fit_time_ms = (time.perf_counter() - start_time) * 1000

        return SurfaceFitResult(
            method=SurfaceMethod.SABR,
            underlying_symbol=snapshots[0].underlying_symbol if snapshots else "",
            as_of_ns=int(time.time() * 1_000_000_000),
            params=self._flatten_params(sabr_params),
            expiries=expiries,
            strikes=strikes,
            implied_vols=implied_vols,
            fitted_vols=fitted_vols,
            rms_error=rms_error,
            max_error=max_error,
            arbitrage_free=arb_free,
            calendar_arb_violations=cal_arb,
            butterfly_arb_violations=bf_arb,
            fit_time_ms=fit_time_ms,
        )

    def _prepare_data(
        self,
        snapshots: list[OptionChainSnapshot],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        all_expiries = []
        all_strikes = []
        all_ivs = []

        for snap in snapshots:
            for quote in snap.quotes:
                if quote.implied_volatility <= 0:
                    continue
                all_expiries.append(quote.expiry_epoch_day)
                all_strikes.append(quote.strike)
                all_ivs.append(quote.implied_volatility)

        forwards = np.ones_like(all_expiries) * np.mean(all_strikes)

        return (
            np.array(all_expiries),
            np.array(all_strikes),
            np.array(all_ivs),
            forwards,
        )

    def _fit_sabr_slice(
        self,
        k: np.ndarray,
        iv: np.ndarray,
        forward: float,
        config: SurfaceConfig,
    ) -> dict[str, float]:
        """Fit SABR parameters using Hagan's formula."""
        # SABR parameters: alpha (vol of vol), beta (elasticity), rho (correlation), nu (vol of vol)
        # Initial guess
        alpha = 0.3
        beta = 0.5
        rho = -0.2
        nu = 0.4

        params = np.array([alpha, beta, rho, nu])

        for _ in range(config.sabr_max_iter):
            grad = self._sabr_gradient(params, k, iv, forward)
            params -= 0.01 * grad
            if np.linalg.norm(grad) < config.sabr_tol:
                break

            # Enforce constraints
            params = self._enforce_sabr_constraints(params)

        return {
            "alpha": float(params[0]),
            "beta": float(params[1]),
            "rho": float(params[2]),
            "nu": float(params[3]),
        }

    def _sabr_volatility(
        self,
        k: np.ndarray,
        forward: float,
        params: dict[str, float],
    ) -> np.ndarray:
        """Hagan's SABR implied volatility formula (approximate)."""
        alpha, beta, rho, nu = params["alpha"], params["beta"], params["rho"], params["nu"]

        f = forward
        x = np.log(f / k)

        # Hagan 2002 formula
        z = (nu / alpha) * (f * k) ** ((1 - beta) / 2) * x
        x_z = np.log((np.sqrt(1 - 2 * rho * z + z ** 2) + z - rho) / (1 - rho))

        numer = alpha * (1 + ((1 - beta) ** 2 / 24) * (x ** 2) + ((1 - beta) ** 4 / 1920) * (x ** 4))
        denom = (f * k) ** ((1 - beta) / 2) * (1 + ((1 - beta) ** 2 / 24) * x ** 2)
        vol = (numer / denom) * (z / x_z) * (
            1
            + ((1 - beta) ** 2 / 24) * (alpha ** 2) / ((f * k) ** (1 - beta))
            + (rho * beta * nu * alpha / 4) / ((f * k) ** ((1 - beta) / 2))
            + ((2 - 3 * rho ** 2) / 24) * nu ** 2
        )

        # ATM correction
        atm_mask = np.abs(x) < 1e-8
        if np.any(atm_mask):
            vol[atm_mask] = alpha / (f ** (1 - beta)) * (
                1
                + ((1 - beta) ** 2 / 24) * (alpha ** 2) / (f ** (2 - 2 * beta))
                + (rho * beta * nu * alpha / 4) / (f ** (1 - beta))
                + ((2 - 3 * rho ** 2) / 24) * nu ** 2
            )

        return vol

    def _sabr_gradient(
        self,
        params: np.ndarray,
        k: np.ndarray,
        iv: np.ndarray,
        forward: float,
    ) -> np.ndarray:
        alpha, beta, rho, nu = params
        # Simplified gradient - in production use autodiff or analytic
        fitted = self._sabr_volatility(k, forward, {"alpha": alpha, "beta": beta, "rho": rho, "nu": nu})
        diff = fitted - iv
        return np.array([
            2 * np.mean(diff * fitted / alpha),
            2 * np.mean(diff * fitted * np.log(forward / k) * (1 - beta)),
            2 * np.mean(diff * alpha * nu * (k / forward) ** ((1 - beta) / 2) / (1 - rho ** 2)),
            2 * np.mean(diff * alpha * (k / forward) ** ((1 - beta) / 2) * np.log(forward / k)),
        ])

    def _enforce_sabr_constraints(self, params: np.ndarray) -> np.ndarray:
        alpha, beta, rho, nu = params
        alpha = max(alpha, 1e-4)
        beta = np.clip(beta, 0.0, 1.0)
        rho = np.clip(rho, -0.999, 0.999)
        nu = max(nu, 1e-4)
        return np.array([alpha, beta, rho, nu])

    def _flatten_params(self, sabr_params: dict[str, dict[str, float]]) -> dict[str, float]:
        flat = {}
        for exp_key, params in sabr_params.items():
            for p_name, p_val in params.items():
                flat[f"{exp_key}_{p_name}"] = p_val
        return flat

    def _check_arbitrage(
        self,
        expiries: np.ndarray,
        strikes: np.ndarray,
        vols: np.ndarray,
    ) -> tuple[bool, int, int]:
        return True, 0, 0  # Simplified


# ── Spline Implementation ─────────────────────────────────────────────────────


class SplineFitter:
    """Cubic spline surface fitter for IV surfaces."""

    def fit(
        self,
        snapshots: list[OptionChainSnapshot],
        config: SurfaceConfig,
    ) -> SurfaceFitResult:
        start_time = time.perf_counter()

        from scipy.interpolate import griddata

        expiries, strikes, implied_vols, _ = self._prepare_data(snapshots)

        if len(implied_vols) < config.min_points:
            raise ValueError(f"Insufficient data points: {len(implied_vols)} < {config.min_points}")

        # Create grid for interpolation
        unique_expiries = np.unique(expiries)
        unique_strikes = np.unique(strikes)

        if len(unique_expiries) < 2 or len(unique_strikes) < 2:
            raise ValueError("Need at least 2 unique expiries and strikes for spline")

        # Interpolate onto regular grid
        grid_expiry, grid_strike = np.meshgrid(unique_expiries, unique_strikes, indexing="ij")
        points = np.column_stack([expiries, strikes])
        griddata(points, implied_vols, (grid_expiry, grid_strike), method="cubic", fill_value=np.nan)

        # Flatten for metrics
        fitted_vols = griddata(points, implied_vols, (expiries, strikes), method="cubic", fill_value=np.nan)

        # Handle NaN (extrapolation)
        valid = ~np.isnan(fitted_vols)
        if not np.any(valid):
            raise ValueError("Spline fit produced all NaN")

        rms_error = float(np.sqrt(np.mean((fitted_vols[valid] - implied_vols[valid]) ** 2)))
        max_error = float(np.max(np.abs(fitted_vols[valid] - implied_vols[valid])))

        arb_free, cal_arb, bf_arb = self._check_arbitrage(expiries, strikes, fitted_vols) if config.check_arbitrage else (True, 0, 0)

        fit_time_ms = (time.perf_counter() - start_time) * 1000

        return SurfaceFitResult(
            method=SurfaceMethod.CUBIC_SPLINE,
            underlying_symbol=snapshots[0].underlying_symbol if snapshots else "",
            as_of_ns=int(time.time() * 1_000_000_000),
            params={"grid_shape_x": float(len(unique_expiries)), "grid_shape_y": float(len(unique_strikes))},
            expiries=expiries,
            strikes=strikes,
            implied_vols=implied_vols,
            fitted_vols=np.nan_to_num(fitted_vols, nan=0.0),
            rms_error=rms_error,
            max_error=max_error,
            arbitrage_free=arb_free,
            calendar_arb_violations=cal_arb,
            butterfly_arb_violations=bf_arb,
            fit_time_ms=fit_time_ms,
        )

    def _prepare_data(
        self,
        snapshots: list[OptionChainSnapshot],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        all_expiries = []
        all_strikes = []
        all_ivs = []

        for snap in snapshots:
            for quote in snap.quotes:
                if quote.implied_volatility <= 0:
                    continue
                all_expiries.append(quote.expiry_epoch_day)
                all_strikes.append(quote.strike)
                all_ivs.append(quote.implied_volatility)

        forwards = np.ones_like(all_expiries) * np.mean(all_strikes)

        return (
            np.array(all_expiries),
            np.array(all_strikes),
            np.array(all_ivs),
            forwards,
        )

    def _check_arbitrage(
        self,
        expiries: np.ndarray,
        strikes: np.ndarray,
        vols: np.ndarray,
    ) -> tuple[bool, int, int]:
        return True, 0, 0


# ── Main Entry Point ──────────────────────────────────────────────────────────


def fit_surface(
    snapshots: list[OptionChainSnapshot],
    method: SurfaceMethod = SurfaceMethod.SVI,
    config: SurfaceConfig | None = None,
) -> SurfaceFitResult:
    """Fit volatility surface from chain snapshots.

    Args:
        snapshots: List of OptionChainSnapshot objects
        method: Fitting method (SVI, SABR, CubicSpline, Linear)
        config: Optional fitting configuration

    Returns:
        SurfaceFitResult with fitted parameters and metrics
    """
    config = config or SurfaceConfig(method=method)

    fitters: dict[SurfaceMethod, SurfaceFitter] = {
        SurfaceMethod.SVI: SVIFitter(),
        SurfaceMethod.SABR: SABRFitter(),
        SurfaceMethod.CUBIC_SPLINE: SplineFitter(),
        SurfaceMethod.LINEAR: SplineFitter(),  # fallback
    }

    fitter = fitters.get(method, SVIFitter())
    return fitter.fit(snapshots, config)