# ─────────────────────────────────────────────────────────────────────────────
# Analytics models — cache and data structures for volatility surfaces.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from google.protobuf import timestamp_pb2
from volpulse.surface import SurfaceFitResult

from volpulse.options.v1 import quote_pb2

logger = logging.getLogger(__name__)

__all__ = [
    "CachedSurface",
    "SurfaceCache",
    "SurfaceCacheConfig",
]


@dataclass(frozen=True, slots=True)
class SurfaceCacheConfig:
    """Configuration for surface cache."""

    max_size: int = 100
    ttl_seconds: float = 30.0  # Time-to-live for cached surfaces


@dataclass(slots=True)
class CachedSurface:
    """Cached surface with metadata."""

    result: SurfaceFitResult
    underlying_symbol: str
    timestamp: float = field(default_factory=time.time)

    def to_proto(self) -> Any:
        """Convert to protobuf VolatilitySurface."""
        result = self.result
        points = []
        for exp, strike, iv, fitted in zip(
            result.expiries,
            result.strikes,
            result.implied_vols,
            result.fitted_vols,
        ):
            points.append(
                quote_pb2.SurfacePoint(
                    expiry_epoch_day=float(exp),
                    strike=float(strike),
                    implied_volatility=float(fitted),
                    fitted_error=float(abs(iv - fitted)),
                )
            )

        ts = timestamp_pb2.Timestamp()
        ts.GetCurrentTime()

        return quote_pb2.VolatilitySurface(
            underlying_symbol=self.underlying_symbol,
            as_of=ts,
            points=points,
            fit_method=result.method.value,
            rms_error=result.rms_error,
            arbitrage_free=result.arbitrage_free,
        )


class SurfaceCache:
    """Thread-safe cache for fitted volatility surfaces."""

    def __init__(self, config: SurfaceCacheConfig) -> None:
        self._config = config
        self._cache: dict[str, CachedSurface] = {}

    def get(self, underlying_symbol: str) -> CachedSurface | None:
        """Get cached surface if not stale."""
        cached = self._cache.get(underlying_symbol)
        if cached is None:
            return None

        if time.time() - cached.timestamp > self._config.ttl_seconds:
            self._cache.pop(underlying_symbol, None)
            return None

        return cached

    def put(self, underlying_symbol: str, result: SurfaceFitResult) -> None:
        """Store surface in cache."""
        self._cache[underlying_symbol] = CachedSurface(
            result=result,
            underlying_symbol=underlying_symbol,
        )

    def invalidate(self, underlying_symbol: str) -> None:
        """Remove surface from cache."""
        self._cache.pop(underlying_symbol, None)

    def clear(self) -> None:
        """Clear all cached surfaces."""
        self._cache.clear()

    def size(self) -> int:
        """Return number of cached surfaces."""
        return len(self._cache)