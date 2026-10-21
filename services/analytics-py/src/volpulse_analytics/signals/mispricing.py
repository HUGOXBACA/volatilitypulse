"""Detection of volatility mispricings against a historical baseline.

A mispricing signal compares the volatility implied by the current market
with the model's fair volatility, and measures the deviation in units of the
historical standard deviation of that deviation. Only deviations beyond a
threshold are actionable; the rest is noise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = ["MispricingSignal", "zscore_mispricing"]


@dataclass(frozen=True, slots=True)
class MispricingSignal:
    """A vector of mispricing verdicts."""

    zscore: NDArray[np.float64]
    model_volatility: NDArray[np.float64]
    observed_volatility: NDArray[np.float64]
    threshold: float

    @property
    def is_significant(self) -> NDArray[np.bool_]:
        """True where the deviation exceeds the threshold."""
        return np.abs(self.zscore) >= self.threshold

    @property
    def direction(self) -> NDArray[np.str_]:
        """``"rich"`` where the market is expensive, ``"cheap"`` where it is not."""
        return np.where(self.zscore > 0.0, "rich", "cheap")


def zscore_mispricing(
    model_volatility: ArrayLike,
    observed_volatility: ArrayLike,
    baseline_mean: ArrayLike,
    baseline_std: ArrayLike,
    *,
    threshold: float = 2.0,
) -> MispricingSignal:
    """Compare observed volatility against a model's fair value.

    The deviation of the observed volatility from the model is normalised by
    the historical dispersion of that deviation, which is what makes the
    signal comparable across expiries and strikes.

    Args:
        model_volatility: Fair volatility from the fitted surface.
        observed_volatility: Volatility implied by the current market.
        baseline_mean: Historical mean of the deviation.
        baseline_std: Historical standard deviation of the deviation.
        threshold: Absolute z-score above which a signal is emitted.

    Returns:
        The z-scores and the inputs they were derived from.
    """
    model = np.asarray(model_volatility, dtype=np.float64)
    observed = np.asarray(observed_volatility, dtype=np.float64)
    mean = np.asarray(baseline_mean, dtype=np.float64)
    std = np.asarray(baseline_std, dtype=np.float64)

    deviation = observed - model
    safe_std = np.where(std > 0.0, std, np.nan)
    zscore = (deviation - mean) / safe_std

    return MispricingSignal(
        zscore=zscore,
        model_volatility=model,
        observed_volatility=observed,
        threshold=threshold,
    )
