# ─────────────────────────────────────────────────────────────────────────────
# Property-based tests for chain builder using Hypothesis.
#
# Tests invariants of OptionChainSnapshot aggregation:
# - Sequence ordering preservation
# - Gap detection accuracy
# - Snapshot emission correctness
# - Underlying/expiry grouping
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
from typing import Any

import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, given, settings

from volpulse_core.chain import ChainBuilder, ChainBuilderConfig
from volpulse_core.models.quote import OptionQuote, OptionRight, QuoteSource

# ── Hypothesis Strategies ─────────────────────────────────────────────────────


@st.composite
def option_quote_strategy(draw: st.DrawFn) -> OptionQuote:
    """Generate a valid OptionQuote."""
    underlying = draw(st.sampled_from(["AAPL", "MSFT", "SPY", "GOOGL", "TSLA"]))
    expiry_day = draw(st.integers(min_value=19000, max_value=21000))
    strike = draw(st.floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
    right = draw(st.sampled_from([OptionRight.CALL, OptionRight.PUT]))
    bid = draw(st.floats(min_value=0.01, max_value=500.0, allow_nan=False, allow_infinity=False))
    ask = draw(st.floats(min_value=bid, max_value=bid + 50.0, allow_nan=False, allow_infinity=False))
    last = draw(st.floats(min_value=bid, max_value=ask, allow_nan=False, allow_infinity=False))
    close = draw(st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False))
    iv = draw(st.floats(min_value=0.01, max_value=2.0, allow_nan=False, allow_infinity=False))
    event_time_ns = draw(st.integers(min_value=1_700_000_000_000_000_000, max_value=1_800_000_000_000_000_000))
    sequence = draw(st.integers(min_value=1, max_value=1_000_000))

    return OptionQuote(
        contract_id=f"{underlying}{expiry_day}{'C' if right == OptionRight.CALL else 'P'}{int(strike * 1000):08d}",
        underlying_symbol=underlying,
        expiry_epoch_day=expiry_day,
        strike=strike,
        right=right,
        bid=bid,
        ask=ask,
        last=last,
        close=close,
        implied_volatility=iv,
        event_time_ns=event_time_ns,
        ingest_time_ns=event_time_ns + 1000,
        sequence=sequence,
        source=QuoteSource.REALTIME_FEED,
    )


@st.composite
def quote_sequence_strategy(draw: st.DrawFn) -> list[OptionQuote]:
    """Generate a sequence of quotes for the same underlying/expiry with increasing sequence numbers."""
    underlying = draw(st.sampled_from(["AAPL", "MSFT", "SPY"]))
    expiry_day = draw(st.integers(min_value=19000, max_value=21000))
    n = draw(st.integers(min_value=1, max_value=100))

    base_seq = draw(st.integers(min_value=1, max_value=1000))
    base_time = draw(st.integers(min_value=1_700_000_000_000_000_000, max_value=1_800_000_000_000_000_000))

    quotes = []
    for i in range(n):
        strike = draw(st.floats(min_value=50.0, max_value=500.0, allow_nan=False, allow_infinity=False))
        right = draw(st.sampled_from([OptionRight.CALL, OptionRight.PUT]))
        bid = draw(st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False))
        ask = draw(st.floats(min_value=bid, max_value=bid + 10.0, allow_nan=False, allow_infinity=False))

        seq = base_seq + i
        event_time = base_time + i * 1_000_000

        quotes.append(
            OptionQuote(
                contract_id=f"{underlying}{expiry_day}{'C' if right == OptionRight.CALL else 'P'}{int(strike * 1000):08d}",
                underlying_symbol=underlying,
                expiry_epoch_day=expiry_day,
                strike=strike,
                right=right,
                bid=bid,
                ask=ask,
                last=(bid + ask) / 2,
                close=ask,
                implied_volatility=draw(st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False)),
                event_time_ns=event_time,
                ingest_time_ns=event_time + 1000,
                sequence=seq,
                source=QuoteSource.REALTIME_FEED,
            )
        )

    return quotes


@st.composite
def multi_underlying_quotes_strategy(draw: st.DrawFn) -> list[OptionQuote]:
    """Generate quotes for multiple underlyings and expiries."""
    underlyings = draw(st.lists(st.sampled_from(["AAPL", "MSFT", "SPY", "GOOGL"]), min_size=1, max_size=3, unique=True))
    n_total = draw(st.integers(min_value=10, max_value=200))

    quotes = []
    base_seq = 1
    base_time = 1_700_000_000_000_000_000

    for _ in range(n_total):
        underlying = draw(st.sampled_from(underlyings))
        expiry_day = draw(st.integers(min_value=19000, max_value=21000))
        strike = draw(st.floats(min_value=50.0, max_value=500.0, allow_nan=False, allow_infinity=False))
        right = draw(st.sampled_from([OptionRight.CALL, OptionRight.PUT]))
        bid = draw(st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False))
        ask = draw(st.floats(min_value=bid, max_value=bid + 10.0, allow_nan=False, allow_infinity=False))

        quotes.append(
            OptionQuote(
                contract_id=f"{underlying}{expiry_day}{'C' if right == OptionRight.CALL else 'P'}{int(strike * 1000):08d}",
                underlying_symbol=underlying,
                expiry_epoch_day=expiry_day,
                strike=strike,
                right=right,
                bid=bid,
                ask=ask,
                last=(bid + ask) / 2,
                close=ask,
                implied_volatility=draw(st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False)),
                event_time_ns=base_time + base_seq * 1_000_000,
                ingest_time_ns=base_time + base_seq * 1_000_000 + 1000,
                sequence=base_seq,
                source=QuoteSource.REALTIME_FEED,
            )
        )
        base_seq += 1
        base_time += 1_000_000

    return quotes


# ── Test Configuration ───────────────────────────────────────────────────────


def make_chain_config(**kwargs: Any) -> ChainBuilderConfig:
    """Create a test ChainBuilderConfig with fast emission."""
    # Default fast config for tests, but allow overrides
    defaults: dict[str, Any] = {
        "snapshot_interval": 0.001,
        "max_buffer_size": 10000,
        "max_sequence_gap": 10,
        "emit_on_every_quote": False,
    }
    defaults.update(kwargs)
    return ChainBuilderConfig(**defaults)


async def collect_snapshots(
    quotes: list[OptionQuote],
    config: ChainBuilderConfig,
) -> list[Any]:
    """Run chain builder and collect emitted snapshots."""
    snapshots: list[Any] = []

    async def handler(snapshot: Any) -> None:
        snapshots.append(snapshot)

    builder = ChainBuilder(config, handler=handler)

    # Start the builder's background tasks
    run_task = asyncio.create_task(builder.run())

    for quote in quotes:
        await builder.add_quote(quote)

    # Wait for emissions
    await asyncio.sleep(0.05)

    # Shutdown
    await builder.shutdown()
    await run_task

    return snapshots


# ── Property Tests ────────────────────────────────────────────────────────────


class TestChainBuilderProperties:
    """Property-based tests for chain builder invariants."""

    @given(quotes=quote_sequence_strategy())
    @settings(
        max_examples=50,
        deadline=5000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_sequence_ordering_preserved(self, quotes: list[OptionQuote]) -> None:
        """Quotes in snapshot must be ordered by sequence number."""
        config = make_chain_config()
        snapshots = await collect_snapshots(quotes, config)

        for snapshot in snapshots:
            sequences = [q.sequence for q in snapshot.quotes]
            assert sequences == sorted(sequences), "Quotes must be ordered by sequence"

    @given(quotes=quote_sequence_strategy())
    @settings(
        max_examples=50,
        deadline=5000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_all_quotes_emitted(self, quotes: list[OptionQuote]) -> None:
        """All input quotes must appear in some snapshot."""
        config = make_chain_config()
        snapshots = await collect_snapshots(quotes, config)

        # Collect all emitted quotes
        emitted_quotes = []
        for snapshot in snapshots:
            emitted_quotes.extend(snapshot.quotes)

        # Every input quote should have a matching emitted quote (by sequence)
        input_sequences = {q.sequence for q in quotes}
        emitted_sequences = {q.sequence for q in emitted_quotes}

        assert input_sequences.issubset(emitted_sequences)

    @given(quotes=quote_sequence_strategy())
    @settings(
        max_examples=50,
        deadline=5000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_snapshot_sequence_monotonic(self, quotes: list[OptionQuote]) -> None:
        """Snapshot sequence numbers must be monotonically increasing."""
        config = make_chain_config()
        snapshots = await collect_snapshots(quotes, config)

        sequences = [s.sequence for s in snapshots]
        assert sequences == sorted(sequences), "Snapshot sequences must be monotonic"

    @given(quotes=multi_underlying_quotes_strategy())
    @settings(
        max_examples=30,
        deadline=10000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_underlying_expiry_grouping(self, quotes: list[OptionQuote]) -> None:
        """Quotes must be grouped by (underlying, expiry) in snapshots."""
        config = make_chain_config()
        snapshots = await collect_snapshots(quotes, config)

        for snapshot in snapshots:
            underlyings = {q.underlying_symbol for q in snapshot.quotes}
            expiries = {q.expiry_epoch_day for q in snapshot.quotes}

            assert len(underlyings) == 1, "Snapshot must have single underlying"
            assert len(expiries) == 1, "Snapshot must have single expiry"

    @given(quotes=quote_sequence_strategy().filter(lambda qs: len(qs) >= 5))
    @settings(
        max_examples=3,
        deadline=10000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_gap_detection(self, quotes: list[OptionQuote]) -> None:
        """Sequence gaps must be detected and counted."""
        # Use a simple deterministic test instead of hypothesis for speed
        pytest.skip("Replaced by deterministic test below")

    @given(quotes=multi_underlying_quotes_strategy())
    @settings(
        max_examples=30,
        deadline=10000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_reported_quote_count_accurate(self, quotes: list[OptionQuote]) -> None:
        """reported_quote_count must match actual quote count in snapshot."""
        config = make_chain_config()
        snapshots = await collect_snapshots(quotes, config)

        for snapshot in snapshots:
            assert snapshot.reported_quote_count == len(snapshot.quotes), \
                f"reported_quote_count ({snapshot.reported_quote_count}) != actual ({len(snapshot.quotes)})"

    @given(n_quotes=st.integers(min_value=1, max_value=500))
    @settings(
        max_examples=20,
        deadline=5000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_high_volume_handling(self, n_quotes: int) -> None:
        """Builder must handle high volume without losing quotes."""
        config = make_chain_config()
        quotes = []
        for i in range(n_quotes):
            quotes.append(
                OptionQuote(
                    contract_id=f"AAPL20000C00150000_{i}",
                    underlying_symbol="AAPL",
                    expiry_epoch_day=20000,
                    strike=150.0 + (i % 100),
                    right=OptionRight.CALL if i % 2 == 0 else OptionRight.PUT,
                    bid=1.0,
                    ask=1.1,
                    last=1.05,
                    close=1.0,
                    implied_volatility=0.25,
                    event_time_ns=1_700_000_000_000_000_000 + i * 1_000_000,
                    ingest_time_ns=1_700_000_000_000_000_000 + i * 1_000_000 + 1000,
                    sequence=i + 1,
                    source=QuoteSource.REALTIME_FEED,
                )
            )

        snapshots = await collect_snapshots(quotes, config)

        total_emitted = sum(len(s.quotes) for s in snapshots)
        assert total_emitted == n_quotes, f"Expected {n_quotes}, got {total_emitted}"

    @given(quotes=quote_sequence_strategy())
    @settings(
        max_examples=30,
        deadline=5000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_concurrent_add_quote(self, quotes: list[OptionQuote]) -> None:
        """Multiple concurrent add_quote calls must not lose quotes."""
        config = make_chain_config()
        builder = ChainBuilder(config)
        run_task = asyncio.create_task(builder.run())

        async def add_batch(batch: list[OptionQuote]) -> None:
            for q in batch:
                await builder.add_quote(q)

        # Split quotes into batches and add concurrently
        batch_size = max(1, len(quotes) // 4)
        batches = [quotes[i:i + batch_size] for i in range(0, len(quotes), batch_size)]

        await asyncio.gather(*[add_batch(b) for b in batches])
        await asyncio.sleep(0.02)
        await builder.shutdown()
        await run_task

        stats = builder.get_stats()
        assert stats["quotes_received"] == len(quotes)


# ── Integration Tests ─────────────────────────────────────────────────────────


class TestChainBuilderIntegration:
    """Integration tests with realistic scenarios."""

    @pytest.mark.asyncio
    async def test_out_of_order_quotes_handled(self) -> None:
        """Quotes arriving out of order must be sorted correctly in snapshot."""
        config = make_chain_config()
        quotes = [
            OptionQuote(
                contract_id=f"AAPL20000C00150000_{i}",
                underlying_symbol="AAPL",
                expiry_epoch_day=20000,
                strike=150.0 + i,
                right=OptionRight.CALL,
                bid=1.0,
                ask=1.1,
                last=1.05,
                close=1.0,
                implied_volatility=0.25,
                event_time_ns=1_700_000_000_000_000_000 + i * 1_000_000,
                ingest_time_ns=1_700_000_000_000_000_000 + i * 1_000_000 + 1000,
                sequence=seq,
                source=QuoteSource.REALTIME_FEED,
            )
            for i, seq in enumerate([5, 1, 3, 2, 4])  # Out of order
        ]

        snapshots = await collect_snapshots(quotes, config)

        for snapshot in snapshots:
            sequences = [q.sequence for q in snapshot.quotes]
            assert sequences == sorted(sequences)

    @pytest.mark.asyncio
    async def test_duplicate_quotes_deduplicated(self) -> None:
        """Duplicate sequence numbers must not create duplicate quotes in snapshot."""
        config = make_chain_config()
        quotes = [
            OptionQuote(
                contract_id=f"AAPL20000C00150000_{i}",
                underlying_symbol="AAPL",
                expiry_epoch_day=20000,
                strike=150.0 + i,
                right=OptionRight.CALL,
                bid=1.0,
                ask=1.1,
                last=1.05,
                close=1.0,
                implied_volatility=0.25,
                event_time_ns=1_700_000_000_000_000_000 + i * 1_000_000,
                ingest_time_ns=1_700_000_000_000_000_000 + i * 1_000_000 + 1000,
                sequence=seq,
                source=QuoteSource.REALTIME_FEED,
            )
            for i, seq in enumerate([1, 2, 2, 3, 4])  # Duplicate seq 2
        ]

        snapshots = await collect_snapshots(quotes, config)

        for snapshot in snapshots:
            sequences = [q.sequence for q in snapshot.quotes]
            assert len(sequences) == len(set(sequences)), "No duplicate sequences in snapshot"

    @pytest.mark.asyncio
    async def test_multiple_expiries_same_underlying(self) -> None:
        """Different expiries for same underlying must create separate snapshots."""
        config = make_chain_config()
        quotes = []
        for expiry in [20000, 20010, 20020]:
            for i in range(5):
                quotes.append(
                    OptionQuote(
                        contract_id=f"AAPL{expiry}C00150000_{i}",
                        underlying_symbol="AAPL",
                        expiry_epoch_day=expiry,
                        strike=150.0 + i,
                        right=OptionRight.CALL,
                        bid=1.0,
                        ask=1.1,
                        last=1.05,
                        close=1.0,
                        implied_volatility=0.25,
                        event_time_ns=1_700_000_000_000_000_000 + (expiry * 1000 + i) * 1_000_000,
                        ingest_time_ns=1_700_000_000_000_000_000 + (expiry * 1000 + i) * 1_000_000 + 1000,
                        sequence=expiry * 1000 + i + 1,
                        source=QuoteSource.REALTIME_FEED,
                    )
                )

        snapshots = await collect_snapshots(quotes, config)

        # Should have 3 snapshots (one per expiry)
        expiries = {s.quotes[0].expiry_epoch_day for s in snapshots if s.quotes}
        assert expiries == {20000, 20010, 20020}

    @pytest.mark.asyncio
    async def test_emit_on_every_quote_mode(self) -> None:
        """emit_on_every_quote=True must emit snapshot for each quote."""
        config = make_chain_config(
            snapshot_interval=10.0,
            emit_on_every_quote=True,
            max_buffer_size=1000,
        )

        quotes = [
            OptionQuote(
                contract_id=f"AAPL20000C00150000_{i}",
                underlying_symbol="AAPL",
                expiry_epoch_day=20000,
                strike=150.0 + i,
                right=OptionRight.CALL,
                bid=1.0,
                ask=1.1,
                last=1.05,
                close=1.0,
                implied_volatility=0.25,
                event_time_ns=1_700_000_000_000_000_000 + i * 1_000_000,
                ingest_time_ns=1_700_000_000_000_000_000 + i * 1_000_000 + 1000,
                sequence=i + 1,
                source=QuoteSource.REALTIME_FEED,
            )
            for i in range(10)
        ]

        snapshots = await collect_snapshots(quotes, config)

        # Should emit one snapshot per quote (since emit_on_every_quote=True)
        assert len(snapshots) == len(quotes)

    @pytest.mark.asyncio
    async def test_shutdown_emits_remaining(self) -> None:
        """Shutdown must emit any remaining buffered quotes."""
        config = make_chain_config()
        quotes = [
            OptionQuote(
                contract_id=f"AAPL20000C00150000_{i}",
                underlying_symbol="AAPL",
                expiry_epoch_day=20000,
                strike=150.0 + i,
                right=OptionRight.CALL,
                bid=1.0,
                ask=1.1,
                last=1.05,
                close=1.0,
                implied_volatility=0.25,
                event_time_ns=1_700_000_000_000_000_000 + i * 1_000_000,
                ingest_time_ns=1_700_000_000_000_000_000 + i * 1_000_000 + 1000,
                sequence=i + 1,
                source=QuoteSource.REALTIME_FEED,
            )
            for i in range(5)
        ]

        builder = ChainBuilder(config)
        run_task = asyncio.create_task(builder.run())
        for q in quotes:
            await builder.add_quote(q)

        # Wait for queue to be processed
        await builder._queue.join()

        # Don't wait for interval, just shutdown
        await builder.shutdown()
        await run_task

        stats = builder.get_stats()
        assert stats["snapshots_emitted"] >= 1
        assert stats["total_buffered_quotes"] == 0

    @pytest.mark.asyncio
    async def test_gap_detection_deterministic(self) -> None:
        """Sequence gaps must be detected and counted (deterministic test)."""
        config = make_chain_config()

        # Create quotes with a known gap: seq 1, 2, 5 (gap of 2)
        quotes = [
            OptionQuote(
                contract_id=f"AAPL20000C00150000_{i}",
                underlying_symbol="AAPL",
                expiry_epoch_day=20000,
                strike=150.0 + i,
                right=OptionRight.CALL,
                bid=1.0,
                ask=1.1,
                last=1.05,
                close=1.0,
                implied_volatility=0.25,
                event_time_ns=1_700_000_000_000_000_000 + i * 1_000_000,
                ingest_time_ns=1_700_000_000_000_000_000 + i * 1_000_000 + 1000,
                sequence=seq,
                source=QuoteSource.REALTIME_FEED,
            )
            for i, seq in enumerate([1, 2, 5, 6, 7])  # Gap between 2 and 5
        ]

        builder = ChainBuilder(config)
        run_task = asyncio.create_task(builder.run())
        for q in quotes:
            await builder.add_quote(q)

        await builder._queue.join()
        await builder.shutdown()
        await run_task

        stats = builder.get_stats()
        # Gap detected: sequence 5 when expected was 3 = gap of 2
        assert stats["gaps_detected"] == 2

    @pytest.mark.asyncio
    async def test_gap_detection_from_non_one_start(self) -> None:
        """Gap detected when first sequence is not 1."""
        config = make_chain_config()

        # First quote has sequence 5 (gap of 4 from expected start 1)
        quotes = [
            OptionQuote(
                contract_id=f"AAPL20000C00150000_{i}",
                underlying_symbol="AAPL",
                expiry_epoch_day=20000,
                strike=150.0 + i,
                right=OptionRight.CALL,
                bid=1.0,
                ask=1.1,
                last=1.05,
                close=1.0,
                implied_volatility=0.25,
                event_time_ns=1_700_000_000_000_000_000 + i * 1_000_000,
                ingest_time_ns=1_700_000_000_000_000_000 + i * 1_000_000 + 1000,
                sequence=seq,
                source=QuoteSource.REALTIME_FEED,
            )
            for i, seq in enumerate([5, 6, 7, 8, 9])  # Start at 5
        ]

        builder = ChainBuilder(config)
        run_task = asyncio.create_task(builder.run())
        for q in quotes:
            await builder.add_quote(q)

        await builder._queue.join()
        await builder.shutdown()
        await run_task

        stats = builder.get_stats()
        # Gap from expected start (1) to first sequence (5) = 4
        assert stats["gaps_detected"] == 4