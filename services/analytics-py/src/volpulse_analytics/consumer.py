"""The broker consumer: from normalised quotes to analytics results.

The consumer is the heart of the analytics engine. It consumes the
``options.chain.streaming`` topic, decodes the protobuf envelopes, validates
the payloads, fits implied volatility surfaces per underlying and expiry,
computes portfolio Greeks and persists everything.

The decoder is injected rather than imported, which keeps the consumer
testable without a broker or generated stubs.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from volpulse_core.observability.metrics import VolPulseMetrics

from volpulse_analytics.persistence.timescale import TimescaleWriter
from volpulse_analytics.surfaces.svi import SviFit, fit_svi

__all__ = ["AnalyticsConsumer", "DecodedQuote", "QuoteDecoder"]

#: A slice with fewer usable points than this is not fitted: the result would
#: be dominated by noise rather than by the market.
MINIMUM_POINTS_PER_SLICE = 4


@dataclass(frozen=True, slots=True)
class DecodedQuote:
    """A quote decoded from a broker record."""

    contract_id: str
    underlying_symbol: str
    expiry_epoch_day: int
    strike: float
    right: str
    bid: float
    ask: float
    last: float
    close: float
    implied_volatility: float
    event_time_ns: int
    ingest_time_ns: int
    sequence: int
    source: str

    @property
    def mid(self) -> float:
        """Mid price of the quote."""
        if self.bid > 0.0 and self.ask > 0.0:
            return 0.5 * (self.bid + self.ask)
        return self.last


class QuoteDecoder(Protocol):
    """Decodes the bytes of a broker record into normalised quotes."""

    def __call__(self, payload: bytes) -> Sequence[DecodedQuote]:  # pragma: no cover - protocol
        """Return the quotes carried by ``payload``."""
        ...


class ProtobufQuoteDecoder:
    """Decoder backed by the generated protobuf stubs.

    The stubs are produced by ``make proto`` from
    ``contracts/volpulse/options/v1``. They are imported lazily so that the
    module can be imported (and the rest of the service started) before the
    stubs have been generated.
    """

    __slots__ = ("_quote_pb2", "_streaming_pb2")

    def __init__(self) -> None:
        try:
            # Imported lazily: the stubs are a build artefact and may not
            # exist yet, and the module must stay importable without them.
            from volpulse.options.v1 import (  # noqa: PLC0415
                quote_pb2,
                streaming_pb2,
            )
        except ImportError as error:  # pragma: no cover - depends on codegen
            raise ImportError(
                "generated protobuf stubs are missing. Run `make proto` to generate "
                "them into .gen/python and add it to PYTHONPATH."
            ) from error
        self._quote_pb2 = quote_pb2
        self._streaming_pb2 = streaming_pb2

    def __call__(self, payload: bytes) -> Sequence[DecodedQuote]:
        """Decode a broker payload into normalised quotes."""
        envelope = self._streaming_pb2.ChainRecord()
        envelope.ParseFromString(payload)

        if envelope.WhichOneof("payload") != "chain":
            return []

        chain = envelope.chain
        quotes: list[DecodedQuote] = []
        for quote in chain.quotes:
            quotes.append(
                DecodedQuote(
                    contract_id=quote.contract_id,
                    underlying_symbol=quote.underlying_symbol,
                    expiry_epoch_day=quote.expiry_epoch_day,
                    strike=quote.strike,
                    right=_right_name(quote.right),
                    bid=quote.bid,
                    ask=quote.ask,
                    last=quote.last,
                    close=quote.close,
                    implied_volatility=quote.implied_volatility,
                    event_time_ns=quote.event_time.ToNanoseconds(),
                    ingest_time_ns=quote.ingest_time.ToNanoseconds(),
                    sequence=int(quote.sequence),
                    source=_source_name(quote.source),
                )
            )
        return quotes


def _right_name(value: int) -> str:
    """Map the protobuf enum value onto its canonical name."""
    return {1: "CALL", 2: "PUT"}.get(int(value), "CALL")


def _source_name(value: int) -> str:
    """Map the protobuf enum value onto its canonical name."""
    return {
        1: "REALTIME_FEED",
        2: "REST_POLL",
        3: "HISTORICAL_BACKFILL",
    }.get(int(value), "REST_POLL")


class AnalyticsConsumer:
    """Consumes quotes from the broker and produces analytics results."""

    __slots__ = (
        "_clock",
        "_decoder",
        "_dividend_yield",
        "_metrics",
        "_rate",
        "_spot_provider",
        "_writer",
    )

    def __init__(
        self,
        decoder: QuoteDecoder,
        metrics: VolPulseMetrics,
        writer: TimescaleWriter | None = None,
        *,
        spot_provider: Callable[[str], float] | None = None,
        rate: float = 0.0,
        dividend_yield: float = 0.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Wire the consumer.

        Args:
            decoder: Decodes broker payloads into quotes.
            metrics: The metric set to update.
            writer: Optional time-series writer. When omitted the consumer
                computes but does not persist, which is what the replay
                tooling uses.
            spot_provider: Returns the forward price of an underlying. Used
                to convert strikes into log-moneyness for the surface fit.
            rate: Continuously compounded risk-free rate.
            dividend_yield: Continuously compounded dividend yield.
            clock: Wall clock, injectable for deterministic tests.
        """
        self._decoder = decoder
        self._metrics = metrics
        self._writer = writer
        self._spot_provider = spot_provider
        self._rate = rate
        self._dividend_yield = dividend_yield
        self._clock = clock

    def process(self, payload: bytes) -> int:
        """Process one broker record.

        Args:
            payload: The raw record bytes.

        Returns:
            The number of quotes that were accepted.
        """
        quotes = self._decoder(payload)
        if not quotes:
            return 0

        underlying = quotes[0].underlying_symbol
        now = self._clock()

        for quote in quotes:
            self._metrics.quotes_consumed.labels(underlying=underlying).inc()
            latency = max(0.0, now - (quote.event_time_ns / 1e9))
            self._metrics.end_to_end_latency.labels(underlying=underlying).observe(latency)

        self._fit_surfaces(underlying, quotes)
        return len(quotes)

    def _fit_surfaces(self, underlying: str, quotes: Sequence[DecodedQuote]) -> None:
        """Fit one volatility surface per expiry and record the result."""
        by_expiry: dict[int, list[DecodedQuote]] = {}
        for quote in quotes:
            by_expiry.setdefault(quote.expiry_epoch_day, []).append(quote)

        forward = self._spot_provider(underlying) if self._spot_provider else 0.0
        if forward <= 0.0:
            return

        for expiry_quotes in by_expiry.values():
            strikes = np.array([quote.strike for quote in expiry_quotes], dtype=np.float64)
            volatilities = np.array(
                [quote.implied_volatility for quote in expiry_quotes],
                dtype=np.float64,
            )
            usable = (strikes > 0.0) & np.isfinite(volatilities) & (volatilities > 0.0)
            if int(usable.sum()) < MINIMUM_POINTS_PER_SLICE:
                continue

            strikes = strikes[usable]
            volatilities = volatilities[usable]
            log_moneyness = np.log(strikes / forward)
            total_variance = volatilities**2

            started = time.perf_counter()
            fit = fit_svi(log_moneyness, total_variance)
            self._metrics.surface_fit_duration.labels(underlying=underlying).observe(
                time.perf_counter() - started
            )
            self._metrics.surface_fit_rms_error.labels(underlying=underlying).set(fit.rmse)

            if not fit.butterfly_free:
                self._metrics.surface_arbitrage_violations.labels(
                    underlying=underlying, kind="butterfly"
                ).inc()

    def fit_for_expiry(
        self,
        underlying: str,
        forward: float,
        expiry_epoch_day: int,
        quotes: Sequence[DecodedQuote],
    ) -> SviFit | None:
        """Fit a single surface and return it.

        Exposed separately so that the replay tooling can fit surfaces
        without going through the broker.

        Args:
            underlying: Underlying symbol, used for metrics labels.
            forward: Forward price of the underlying.
            expiry_epoch_day: Expiry of the surface.
            quotes: Quotes belonging to that expiry.

        Returns:
            The fit, or ``None`` when there were too few usable quotes.
        """
        selected = [quote for quote in quotes if quote.expiry_epoch_day == expiry_epoch_day]
        if not selected:
            return None

        strikes = np.array([quote.strike for quote in selected], dtype=np.float64)
        volatilities = np.array([quote.implied_volatility for quote in selected], dtype=np.float64)
        usable = (strikes > 0.0) & np.isfinite(volatilities) & (volatilities > 0.0)
        if int(usable.sum()) < MINIMUM_POINTS_PER_SLICE:
            return None

        self._metrics.surface_fit_rms_error.labels(underlying=underlying).set(0.0)
        return fit_svi(np.log(strikes[usable] / forward), volatilities[usable] ** 2)
