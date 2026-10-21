"""Tests for the SVI surface construction."""

from __future__ import annotations

import numpy as np
import pytest

from volpulse_analytics.surfaces.svi import (
    SviParams,
    check_butterfly_arbitrage,
    check_calendar_arbitrage,
    fit_svi,
    log_moneyness,
)

#: A reference slice that is comfortably inside the arbitrage-free region.
REFERENCE_SURFACE = SviParams(a=0.05, b=0.03, rho=-0.10, m=0.0, sigma=0.60)


def _synthetic_surface(
    k: np.ndarray,
    params: SviParams = REFERENCE_SURFACE,
) -> np.ndarray:
    """Total variance of a reference surface."""
    return params.total_variance(k)


def test_log_moneyness() -> None:
    """Log-moneyness is the log of the strike over the forward."""
    assert float(log_moneyness(100.0, 100.0)) == pytest.approx(0.0)
    assert float(log_moneyness(110.0, 100.0)) == pytest.approx(np.log(1.1))


def test_log_moneyness_rejects_a_non_positive_forward() -> None:
    """A non-positive forward is meaningless."""
    with pytest.raises(ValueError):
        log_moneyness(100.0, 0.0)


def test_fit_recovers_a_known_surface() -> None:
    """Fitting a synthetic surface must recover its parameters."""
    reference = SviParams(a=0.05, b=0.03, rho=-0.10, m=0.0, sigma=0.60)
    k = np.linspace(-0.6, 0.6, 41)
    w = _synthetic_surface(k, reference)

    fit = fit_svi(k, w)

    assert fit.params.a == pytest.approx(reference.a, abs=2e-3)
    assert fit.params.b == pytest.approx(reference.b, abs=2e-3)
    assert fit.params.rho == pytest.approx(reference.rho, abs=2e-2)
    assert fit.params.m == pytest.approx(reference.m, abs=2e-2)
    assert fit.params.sigma == pytest.approx(reference.sigma, abs=2e-2)
    assert fit.rmse < 1e-6
    assert fit.observations == 41


def test_fit_rejects_invalid_input() -> None:
    """The fitter must refuse to work on garbage."""
    with pytest.raises(ValueError):
        fit_svi([], [])
    with pytest.raises(ValueError):
        fit_svi([0.0, 0.1], [0.04])
    with pytest.raises(ValueError):
        fit_svi([0.0, 0.1], [0.04, -0.01])


def test_reference_surface_is_butterfly_free() -> None:
    """A sensible surface must pass the arbitrage check."""
    reference = SviParams(a=0.05, b=0.03, rho=-0.10, m=0.0, sigma=0.60)
    assert check_butterfly_arbitrage(reference)


def test_a_butterfly_arbitrageable_surface_is_rejected() -> None:
    """A surface whose density would go negative must be rejected.

    Lee's moment formula gives the density implied by the slice. Where it
    turns negative the curve allows a butterfly arbitrage, and the surface
    must not be traded on.
    """
    arbitrageable = SviParams(a=0.02, b=0.04, rho=0.30, m=0.0, sigma=0.40)
    assert not check_butterfly_arbitrage(arbitrageable)


def test_a_surface_with_an_undefined_density_is_rejected() -> None:
    """A slice whose density does not exist must be rejected."""
    undefined = SviParams(a=0.04, b=0.06, rho=-0.20, m=0.0, sigma=0.40)
    assert not check_butterfly_arbitrage(undefined)


def test_a_calendar_violating_pair_is_detected() -> None:
    """Total variance must not decrease with time."""
    k = np.linspace(-0.3, 0.3, 31)
    short_expiry = (k, np.full_like(k, 0.02))
    long_expiry = (k, np.full_like(k, 0.01))  # less variance further out

    assert not check_calendar_arbitrage({0.25: short_expiry, 1.0: long_expiry})


def test_a_well_ordered_pair_passes_the_calendar_check() -> None:
    """Variance that grows with time must be accepted."""
    k = np.linspace(-0.3, 0.3, 31)
    short_expiry = (k, np.full_like(k, 0.02))
    long_expiry = (k, np.full_like(k, 0.08))

    assert check_calendar_arbitrage({0.25: short_expiry, 1.0: long_expiry})


def test_a_single_expiry_has_no_calendar_arbitrage() -> None:
    """One expiry cannot violate the calendar ordering."""
    k = np.linspace(-0.3, 0.3, 11)
    assert check_calendar_arbitrage({0.5: (k, np.full_like(k, 0.02))})
