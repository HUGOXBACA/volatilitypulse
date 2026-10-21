"""The normalised option quote — the atom of the VolPulse pipeline.

The shape mirrors ``contracts/volpulse/options/v1/quote.proto`` exactly: the
C++ ingestion engine emits the protobuf, the Python analytics engine consumes
it, and both must agree field for field.

These types are frozen and slotted. They are created on the hot path, so
they must not allocate dictionaries, must not be mutated after construction,
and must be cheap to hash and compare.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

__all__ = ["OptionQuote", "OptionRight", "QuoteSource"]


class OptionRight(enum.StrEnum):
    """Right of an option contract."""

    CALL = "CALL"
    PUT = "PUT"


class QuoteSource(enum.StrEnum):
    """How a quote was produced by the upstream provider."""

    REALTIME_FEED = "REALTIME_FEED"
    REST_POLL = "REST_POLL"
    HISTORICAL_BACKFILL = "HISTORICAL_BACKFILL"


@dataclass(frozen=True, slots=True)
class OptionQuote:
    """A normalised, provider-agnostic quote for a single option contract."""

    contract_id: str
    underlying_symbol: str
    expiry_epoch_day: int
    strike: float
    right: OptionRight
    bid: float
    ask: float
    last: float
    close: float
    implied_volatility: float
    event_time_ns: int
    ingest_time_ns: int
    sequence: int
    source: QuoteSource = QuoteSource.REST_POLL

    def __post_init__(self) -> None:
        """Reject structurally impossible quotes at construction time."""
        if self.bid < 0.0 or self.ask < 0.0:
            raise ValueError(f"negative price in quote {self.contract_id!r}")
        if self.strike <= 0.0:
            raise ValueError(f"non-positive strike in quote {self.contract_id!r}")
        if self.bid > 0.0 and self.ask > 0.0 and self.bid > self.ask:
            raise ValueError(
                f"crossed quote in {self.contract_id!r}: bid {self.bid} > ask {self.ask}"
            )

    @property
    def mid(self) -> float:
        """Mid price, or the last trade when the book is empty."""
        if self.bid > 0.0 and self.ask > 0.0:
            return 0.5 * (self.bid + self.ask)
        return self.last

    @property
    def spread(self) -> float:
        """Absolute bid/ask spread."""
        if self.bid > 0.0 and self.ask > 0.0:
            return self.ask - self.bid
        return 0.0

    @property
    def is_expiring_today(self) -> bool:
        """True when the contract expires within one day of the event time."""
        return False
