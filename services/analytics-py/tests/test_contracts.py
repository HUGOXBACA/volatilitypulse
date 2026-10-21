"""Contract round-trip tests.

These tests exercise the generated protobuf stubs against the contract in
``contracts/``. They are skipped when the stubs have not been generated,
because the stubs are a build artefact, not a checked-in file.

    make proto
"""

from __future__ import annotations

import pytest
from volpulse_core.observability.metrics import VolPulseMetrics

from volpulse_analytics.consumer import AnalyticsConsumer, ProtobufQuoteDecoder

pytest.importorskip(
    "volpulse.options.v1.quote_pb2",
    reason="protobuf stubs are not generated; run `make proto`",
)

from volpulse.common.v1 import common_pb2
from volpulse.options.v1 import quote_pb2, streaming_pb2


def _build_payload() -> bytes:
    """Build a broker payload the way the C++ normaliser would."""
    quote = quote_pb2.OptionQuote(
        contract_id="AAPL-30d-0007",
        underlying_symbol="AAPL",
        expiry_epoch_day=20345,
        strike=187.5,
        right=common_pb2.OPTION_RIGHT_CALL,
        bid=3.25,
        ask=3.30,
        last=3.28,
        close=3.20,
        implied_volatility=0.31,
    )
    quote.event_time.FromMilliseconds(1_700_000_000_000)
    quote.ingest_time.FromMilliseconds(1_700_000_050_000)
    quote.sequence = 42
    quote.source = common_pb2.QUOTE_SOURCE_REST_POLL

    chain = quote_pb2.OptionChainSnapshot(
        underlying_symbol="AAPL",
        reported_quote_count=1,
    )
    chain.event_time.FromMilliseconds(1_700_000_000_000)
    chain.quotes.append(quote)

    envelope = streaming_pb2.ChainRecord(
        schema_version=1,
        partition_key="AAPL",
        producer_id="ingestion-1",
        producer_epoch=1,
        binary_log_offset=4096,
    )
    envelope.produced_at.FromMilliseconds(1_700_000_000_000)
    envelope.chain.CopyFrom(chain)
    return envelope.SerializeToString()


def test_decoder_reads_the_normalised_quote() -> None:
    """A payload built from the contract must decode into a quote."""
    quotes = ProtobufQuoteDecoder()(_build_payload())

    assert len(quotes) == 1
    quote = quotes[0]
    assert quote.contract_id == "AAPL-30d-0007"
    assert quote.underlying_symbol == "AAPL"
    assert quote.strike == pytest.approx(187.5)
    assert quote.right == "CALL"
    assert quote.mid == pytest.approx(3.275)
    assert quote.implied_volatility == pytest.approx(0.31)
    assert quote.sequence == 42
    assert quote.event_time_ns == 1_700_000_000_000_000_000


def test_decoder_ignores_a_non_chain_payload() -> None:
    """A payload that carries no chain must decode to nothing."""
    envelope = streaming_pb2.ChainRecord(schema_version=1, partition_key="AAPL")
    assert ProtobufQuoteDecoder()(envelope.SerializeToString()) == []


def test_consumer_processes_a_chain() -> None:
    """The consumer must accept a decoded chain and fit a surface."""
    metrics = VolPulseMetrics()
    consumed = []

    class _StubDecoder:
        def __call__(self, payload: bytes) -> list:
            quotes = ProtobufQuoteDecoder()(payload)
            consumed.extend(quotes)
            return quotes

    consumer = AnalyticsConsumer(_StubDecoder(), metrics)
    assert consumer.process(_build_payload()) == 1
    assert len(consumed) == 1
