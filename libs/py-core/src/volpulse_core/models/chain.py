"""Chain-level and portfolio-level domain models."""

from __future__ import annotations

from dataclasses import dataclass, field

from volpulse_core.models.quote import OptionQuote

__all__ = ["OptionChainSnapshot", "PortfolioPosition"]


@dataclass(frozen=True, slots=True)
class OptionChainSnapshot:
    """Every quote for one underlying at a point in time."""

    underlying_symbol: str
    event_time_ns: int
    sequence: int
    quotes: tuple[OptionQuote, ...] = ()
    reported_quote_count: int = 0

    @property
    def is_truncated(self) -> bool:
        """True when ingestion dropped quotes relative to the provider count."""
        return self.reported_quote_count > len(self.quotes)


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    """A net position in a single option contract."""

    contract_id: str
    underlying_symbol: str
    strike: float
    right: str
    quantity: float
    avg_entry_price: float
    opened_at_ns: int
    tags: tuple[str, ...] = field(default=())
