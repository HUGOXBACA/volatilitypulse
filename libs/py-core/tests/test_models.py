"""Tests for the domain models."""

from __future__ import annotations

import dataclasses

import pytest

from volpulse_core.models.chain import OptionChainSnapshot
from volpulse_core.models.quote import OptionQuote, OptionRight, QuoteSource


def _quote(**overrides: object) -> OptionQuote:
    """Build a valid quote, overriding individual fields."""
    fields: dict[str, object] = {
        "contract_id": "opt-1",
        "underlying_symbol": "AAPL",
        "expiry_epoch_day": 20000,
        "strike": 187.5,
        "right": OptionRight.CALL,
        "bid": 3.25,
        "ask": 3.30,
        "last": 3.28,
        "close": 3.20,
        "implied_volatility": 0.31,
        "event_time_ns": 1_700_000_000_000_000_000,
        "ingest_time_ns": 1_700_000_000_100_000_000,
        "sequence": 1,
        "source": QuoteSource.REST_POLL,
    }
    fields.update(overrides)
    return OptionQuote(**fields)  # type: ignore[arg-type]


def test_mid_and_spread() -> None:
    """Mid price and spread are derived from the book."""
    quote = _quote()
    assert quote.mid == pytest.approx(3.275)
    assert quote.spread == pytest.approx(0.05)


def test_mid_falls_back_to_the_last_trade() -> None:
    """An empty book falls back to the last traded price."""
    quote = _quote(bid=0.0, ask=0.0)
    assert quote.mid == pytest.approx(3.28)
    assert quote.spread == 0.0


def test_crossed_quotes_are_rejected() -> None:
    """A quote with bid above ask is structurally impossible."""
    with pytest.raises(ValueError, match="crossed"):
        _quote(bid=3.40, ask=3.30)


def test_negative_prices_are_rejected() -> None:
    """A quote with a negative price is structurally impossible."""
    with pytest.raises(ValueError, match="negative"):
        _quote(bid=-1.0)


def test_non_positive_strike_is_rejected() -> None:
    """A quote with a non-positive strike is structurally impossible."""
    with pytest.raises(ValueError, match="strike"):
        _quote(strike=0.0)


def test_quote_is_immutable() -> None:
    """Quotes are frozen: they are shared between components."""
    quote = _quote()
    with pytest.raises(dataclasses.FrozenInstanceError):
        quote.strike = 1.0  # type: ignore[misc]


def test_chain_reports_truncation() -> None:
    """A chain that lost quotes must say so."""
    chain = OptionChainSnapshot(
        underlying_symbol="AAPL",
        event_time_ns=1,
        sequence=1,
        quotes=(_quote(),),
        reported_quote_count=10,
    )
    assert chain.is_truncated
