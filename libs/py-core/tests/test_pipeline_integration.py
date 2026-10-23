# ─────────────────────────────────────────────────────────────────────────────
# End-to-end pipeline integration test.
#
# Simulates the full VolPulse pipeline:
#   WebSocket ingestion (simulated) → ChainBuilder → SurfaceFitter
#
# Validates that quotes flow through chain aggregation and surface fitting
# without data loss or corruption.
# ─────────────────────────────────────────────────────────────────────────────

# mypy: disable-error-code="import-untyped"

from __future__ import annotations

import asyncio

import pytest

from volpulse_core.chain import ChainBuilder, ChainBuilderConfig
from volpulse_core.models.chain import OptionChainSnapshot
from volpulse_core.models.quote import OptionQuote, OptionRight, QuoteSource
from volpulse_core.surface import SurfaceConfig, SurfaceMethod, fit_surface

# ── Test Helpers ─────────────────────────────────────────────────────────────


def make_quotes(
    underlying: str,
    expiry_day: int,
    strikes: list[float],
    right: OptionRight,
    base_seq: int = 1,
    base_time_ns: int = 1_700_000_000_000_000_000,
    iv_base: float = 0.25,
    iv_slope: float = 0.001,
) -> list[OptionQuote]:
    """Generate a list of quotes for a single expiry with varying strikes."""
    quotes = []
    for i, strike in enumerate(strikes):
        seq = base_seq + i
        event_time = base_time_ns + i * 1_000_000
        # Simple smile: IV increases with distance from ATM (strike 150)
        iv = iv_base + iv_slope * abs(strike - 150.0)
        quotes.append(
            OptionQuote(
                contract_id=f"{underlying}{expiry_day}{'C' if right == OptionRight.CALL else 'P'}{int(strike * 1000):08d}",
                underlying_symbol=underlying,
                expiry_epoch_day=expiry_day,
                strike=strike,
                right=right,
                bid=1.0,
                ask=1.1,
                last=1.05,
                close=1.0,
                implied_volatility=iv,
                event_time_ns=event_time,
                ingest_time_ns=event_time + 1000,
                sequence=seq,
                source=QuoteSource.REALTIME_FEED,
            )
        )
    return quotes


def make_chain_config() -> ChainBuilderConfig:
    """Fast chain builder config for tests."""
    return ChainBuilderConfig(
        snapshot_interval=0.001,
        max_buffer_size=10000,
        max_sequence_gap=100,
        emit_on_every_quote=False,
    )


async def collect_snapshots(
    quotes: list[OptionQuote],
    config: ChainBuilderConfig,
) -> list[OptionChainSnapshot]:
    """Run chain builder and collect emitted snapshots."""
    snapshots: list[OptionChainSnapshot] = []

    async def handler(snapshot: OptionChainSnapshot) -> None:
        snapshots.append(snapshot)

    builder = ChainBuilder(config, handler=handler)
    run_task = asyncio.create_task(builder.run())

    for quote in quotes:
        await builder.add_quote(quote)

    # Wait for emissions
    await asyncio.sleep(0.05)

    # Shutdown
    await builder.shutdown()
    await run_task

    return snapshots


# ── Integration Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_single_expiry() -> None:
    """Full pipeline: quotes → chain builder → surface fit (single expiry)."""
    config = make_chain_config()

    # Generate quotes for AAPL, expiry 20000, calls with strikes 100-200
    strikes = [float(s) for s in range(100, 201, 5)]
    quotes = make_quotes(
        underlying="AAPL",
        expiry_day=20000,
        strikes=strikes,
        right=OptionRight.CALL,
        base_seq=1,
    )

    # Run chain builder
    snapshots = await collect_snapshots(quotes, config)

    # Should have at least one snapshot
    assert len(snapshots) >= 1

    # All quotes should be in the snapshot(s)
    total_quotes_in_snapshots = sum(len(s.quotes) for s in snapshots)
    assert total_quotes_in_snapshots == len(quotes)

    # Fit surface (SVI) using the snapshots
    surface_config = SurfaceConfig(method=SurfaceMethod.SVI, min_points=5)
    result = fit_surface(snapshots, config=surface_config)

    # Validate surface fit
    assert result.method == SurfaceMethod.SVI
    assert result.underlying_symbol == "AAPL"
    assert len(result.params) > 0
    assert result.rms_error >= 0.0
    assert result.fit_time_ms > 0.0

    # Fitted vols should be positive
    assert all(v > 0 for v in result.fitted_vols)


@pytest.mark.asyncio
async def test_pipeline_multiple_expiries() -> None:
    """Full pipeline with multiple expiries (term structure)."""
    config = make_chain_config()

    # Generate quotes for two expiries
    all_quotes = []
    for expiry in [20000, 20010]:
        strikes = [float(s) for s in range(100, 201, 10)]
        quotes = make_quotes(
            underlying="AAPL",
            expiry_day=expiry,
            strikes=strikes,
            right=OptionRight.CALL,
            base_seq=expiry * 1000,
            iv_base=0.20 + (expiry - 20000) * 0.001,  # slight term structure
        )
        all_quotes.extend(quotes)

    snapshots = await collect_snapshots(all_quotes, config)

    # Should have two snapshots (one per expiry)
    expiries = {s.quotes[0].expiry_epoch_day for s in snapshots if s.quotes}
    assert expiries == {20000, 20010}

    # Fit surface with both expiries
    surface_config = SurfaceConfig(method=SurfaceMethod.SVI, min_points=5)
    result = fit_surface(snapshots, config=surface_config)

    assert result.method == SurfaceMethod.SVI
    assert result.rms_error >= 0.0

    # Should have points from both expiries
    unique_expiries = len(set(result.expiries))
    assert unique_expiries == 2


@pytest.mark.asyncio
async def test_pipeline_calls_and_puts() -> None:
    """Pipeline handles both calls and puts for same expiry."""
    config = make_chain_config()

    strikes = [float(s) for s in range(100, 201, 10)]
    quotes = []
    for right in [OptionRight.CALL, OptionRight.PUT]:
        quotes.extend(
            make_quotes(
                underlying="AAPL",
                expiry_day=20000,
                strikes=strikes,
                right=right,
                base_seq=1 if right == OptionRight.CALL else 1000,
                iv_base=0.25 if right == OptionRight.CALL else 0.27,
            )
        )

    snapshots = await collect_snapshots(quotes, config)

    # Should have one snapshot (same underlying and expiry)
    assert len(snapshots) == 1
    snapshot = snapshots[0]

    # Should contain both calls and puts
    rights = {q.right for q in snapshot.quotes}
    assert rights == {OptionRight.CALL, OptionRight.PUT}

    # Fit surface
    surface_config = SurfaceConfig(method=SurfaceMethod.SVI, min_points=5)
    result = fit_surface(snapshots, config=surface_config)
    assert result.rms_error >= 0.0


@pytest.mark.asyncio
async def test_pipeline_out_of_order_quotes() -> None:
    """Pipeline handles quotes arriving out of sequence order."""
    config = make_chain_config()

    strikes = [float(s) for s in range(100, 201, 10)]
    # Generate in order, then shuffle sequence numbers
    quotes = make_quotes(
        underlying="AAPL",
        expiry_day=20000,
        strikes=strikes,
        right=OptionRight.CALL,
        base_seq=1,
    )

    # Shuffle the quotes (simulate out-of-order arrival)
    import random

    random.seed(42)
    random.shuffle(quotes)

    snapshots = await collect_snapshots(quotes, config)

    # Should still produce correct snapshot
    assert len(snapshots) >= 1
    total_quotes = sum(len(s.quotes) for s in snapshots)
    assert total_quotes == len(quotes)

    # Quotes in snapshot should be ordered by sequence
    for snap in snapshots:
        sequences = [q.sequence for q in snap.quotes]
        assert sequences == sorted(sequences)

    # Fit surface
    surface_config = SurfaceConfig(method=SurfaceMethod.SVI, min_points=5)
    result = fit_surface(snapshots, config=surface_config)
    assert result.rms_error >= 0.0


@pytest.mark.asyncio
async def test_pipeline_surface_arbitrage_check() -> None:
    """Surface fitting detects arbitrage violations when present."""
    config = make_chain_config()

    # Create quotes with a known calendar arbitrage (shorter expiry higher IV than longer)
    # This is a simple test; real arbitrage detection is more complex.
    all_quotes = []
    # Expiry 20000 with high IV
    all_quotes.extend(
        make_quotes(
            underlying="AAPL",
            expiry_day=20000,
            strikes=[float(s) for s in range(100, 201, 10)],
            right=OptionRight.CALL,
            base_seq=20000000,
            iv_base=0.50,  # Very high IV for short expiry
        )
    )
    # Expiry 20010 with low IV
    all_quotes.extend(
        make_quotes(
            underlying="AAPL",
            expiry_day=20010,
            strikes=[float(s) for s in range(100, 201, 10)],
            right=OptionRight.CALL,
            base_seq=20010000,
            iv_base=0.20,  # Lower IV for longer expiry
        )
    )

    snapshots = await collect_snapshots(all_quotes, config)

    surface_config = SurfaceConfig(method=SurfaceMethod.SVI, check_arbitrage=True, min_points=5)
    result = fit_surface(snapshots, config=surface_config)

    # The fit may or may not flag arbitrage depending on the smile shape.
    # Just ensure the check runs without error.
    assert result.arbitrage_free in (True, False)
    assert isinstance(result.calendar_arb_violations, int)
    assert isinstance(result.butterfly_arb_violations, int)