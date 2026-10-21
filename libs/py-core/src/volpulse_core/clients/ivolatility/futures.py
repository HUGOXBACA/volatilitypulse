# ─────────────────────────────────────────────────────────────────────────────
# Futures endpoint helpers.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from typing import cast

import polars as pl

from volpulse_core.clients.ivolatility.client import IVolatilityClient
from volpulse_core.clients.ivolatility.endpoints import Endpoints


async def futures_prices(
    client: IVolatilityClient,
    *,
    root_symbol: str | None = None,
    future_symbols: str | None = None,
    exp_date: str | None = None,
) -> pl.DataFrame:
    """Realtime futures chain prices for one root symbol or symbol list."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.FUTURES_PRICES,
            rootSymbol=root_symbol,
            futureSymbols=future_symbols,
            expDate=exp_date,
        ),
    )


async def futures_rt_prices(
    client: IVolatilityClient,
    *,
    root_symbol: str | None = None,
    future_symbols: str | None = None,
    exp_date: str | None = None,
) -> pl.DataFrame:
    """Realtime futures prices (KR feed)."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.FUTURES_RT_PRICES,
            rootSymbol=root_symbol,
            futureSymbols=future_symbols,
            expDate=exp_date,
        ),
    )


async def futures_options(
    client: IVolatilityClient,
    *,
    future_symbol: str,
    opt_exp_date: str | None = None,
    moneyness: str,
    opt_type: str | None = None,
) -> pl.DataFrame:
    """Realtime futures options chain for one future."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.FUTURES_OPTIONS,
            futureSymbol=future_symbol,
            optExpDate=opt_exp_date,
            moneyness=moneyness,
            optType=opt_type,
        ),
    )


async def futures_rt_options_rawiv(
    client: IVolatilityClient,
    *,
    future_symbol: str,
    opt_exp_date: str | None = None,
    moneyness: str,
    opt_type: str | None = None,
) -> pl.DataFrame:
    """Realtime futures options with raw IV."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.FUTURES_RT_OPTIONS_RAWIV,
            futureSymbol=future_symbol,
            optExpDate=opt_exp_date,
            moneyness=moneyness,
            optType=opt_type,
        ),
    )


async def futures_market_structure(
    client: IVolatilityClient, *, future_symbol: str
) -> pl.DataFrame:
    """Futures options market structure for one future."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.FUTURES_MARKET_STRUCTURE, futureSymbol=future_symbol
        ),
    )


async def futures_fut_opt_market_structure(
    client: IVolatilityClient, *, future_symbol: str
) -> pl.DataFrame:
    """RT futures options market structure for one future."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.FUTURES_FUT_OPT_MARKET_STRUCTURE,
            futureSymbol=future_symbol,
        ),
    )


async def futures_eod_prices(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    region: str = "USA",
) -> pl.DataFrame:
    """EOD futures prices."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.FUTURES_EOD_PRICES,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            region=region,
        ),
    )


async def futures_eod_options_rawiv(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    region: str = "USA",
) -> pl.DataFrame:
    """EOD futures options raw IV."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.FUTURES_EOD_OPTIONS_RAWIV,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            region=region,
        ),
    )


async def futures_eod_options_nbbo(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    region: str = "USA",
) -> pl.DataFrame:
    """EOD futures options NBBO."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.FUTURES_EOD_OPTIONS_NBBO,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            region=region,
        ),
    )


async def futures_eod_ivx(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    region: str = "USA",
) -> pl.DataFrame:
    """EOD futures IVX."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.FUTURES_EOD_IVX,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            region=region,
        ),
    )


async def futures_eod_ivs(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    region: str = "USA",
) -> pl.DataFrame:
    """EOD futures IV surface."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.FUTURES_EOD_IVS,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            region=region,
        ),
    )


async def futures_eod_hv(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    region: str = "USA",
) -> pl.DataFrame:
    """EOD futures historical volatility."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.FUTURES_EOD_HV,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            region=region,
        ),
    )
