# ─────────────────────────────────────────────────────────────────────────────
# Equity endpoint helpers.
#
# Each function wraps an :class:`Endpoints` definition with the correct query
# parameters and returns a Polars DataFrame. They are thin wrappers around
# :meth:`IVolatilityClient.fetch` so that adding a new endpoint is a matter of
# declaring it in :mod:`endpoints` and adding one function here.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from typing import cast

import polars as pl

from volpulse_core.clients.ivolatility.client import IVolatilityClient
from volpulse_core.clients.ivolatility.endpoints import Endpoints


async def equity_stock_prices(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    region: str = "USA",
) -> pl.DataFrame:
    """Daily EOD prices for one equity."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.EQUITY_STOCK_PRICES,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            region=region,
        ),
    )


async def equity_options_rawiv(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    region: str = "USA",
) -> pl.DataFrame:
    """EOD options chain with IV and Greeks for one equity."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.EQUITY_OPTIONS_RAWIV,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            region=region,
        ),
    )


async def equity_options_nbbo(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    region: str = "USA",
) -> pl.DataFrame:
    """EOD NBBO for one equity's options chain."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.EQUITY_OPTIONS_NBBO,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            region=region,
        ),
    )


async def equity_ivx(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    region: str = "USA",
) -> pl.DataFrame:
    """EOD implied-volatility index for one equity."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.EQUITY_IVX,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            region=region,
        ),
    )


async def equity_ivs(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    region: str = "USA",
) -> pl.DataFrame:
    """EOD implied-volatility surface for one equity."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.EQUITY_IVS,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            region=region,
        ),
    )


async def equity_hv(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    region: str = "USA",
) -> pl.DataFrame:
    """EOD historical volatility for one equity."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.EQUITY_HV,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            region=region,
        ),
    )


async def equity_option_series(
    client: IVolatilityClient,
    *,
    symbol: str,
    exp_from: str | None = None,
    exp_to: str | None = None,
    strike_from: float | None = None,
    strike_to: float | None = None,
    call_put: str | None = None,
) -> pl.DataFrame:
    """EOD option series (chain metadata) for one equity."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.EQUITY_OPTION_SERIES,
            symbol=symbol,
            expFrom=exp_from,
            expTo=exp_to,
            strikeFrom=strike_from,
            strikeTo=strike_to,
            callPut=call_put,
        ),
    )


async def equity_nearest_option_tickers(
    client: IVolatilityClient,
    *,
    symbol: str,
    dte: int,
    starting_date: str | None = None,
    moneyness: int | None = None,
    delta: float | None = None,
    call_put: str | None = None,
) -> pl.DataFrame:
    """Nearest option tickers for one equity and days-to-expiration."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.EQUITY_NEAREST_OPTION_TICKERS,
            symbol=symbol,
            startingDate=starting_date,
            dte=dte,
            moneyness=moneyness,
            delta=delta,
            callPut=call_put,
        ),
    )


async def equity_underlying_info(
    client: IVolatilityClient, *, symbol: str, region: str = "USA"
) -> pl.DataFrame:
    """Reference information for one equity."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.EQUITY_UNDERLYING_INFO, symbol=symbol, region=region
        ),
    )


async def equity_yield(client: IVolatilityClient, *, symbol: str) -> pl.DataFrame:
    """12-month average dividend yield for one equity index."""
    return cast(
        pl.DataFrame,
        await client.fetch(Endpoints.EQUITY_YIELD, symbol=symbol),
    )


async def equity_interest_rates(
    client: IVolatilityClient, *, from_: str, to: str
) -> pl.DataFrame:
    """Interpolated inter-bank offered rates for a date range."""
    return cast(
        pl.DataFrame,
        await client.fetch(Endpoints.EQUITY_INTEREST_RATES, from_=from_, to=to),
    )


async def equity_rt_stock_prices(
    client: IVolatilityClient, *, symbol: str
) -> pl.DataFrame:
    """Realtime price and volume for one equity."""
    return cast(
        pl.DataFrame,
        await client.fetch(Endpoints.EQUITY_RT_STOCK_PRICES, symbol=symbol),
    )


async def equity_rt_options_rawiv(
    client: IVolatilityClient, *, symbols: str
) -> pl.DataFrame:
    """Realtime options data for comma-separated option symbols."""
    return cast(
        pl.DataFrame,
        await client.fetch(Endpoints.EQUITY_RT_OPTIONS_RAWIV, symbols=symbols),
    )


async def equity_intraday_stock_prices(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    minute_type: str | None = None,
    minutes: str | None = None,
) -> pl.DataFrame:
    """Intraday historical prices for one equity."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.EQUITY_INTRADAY_STOCK_PRICES,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            minuteType=minute_type,
            minutes=minutes,
        ),
    )


async def equity_intraday_options_rawiv(
    client: IVolatilityClient,
    *,
    symbol: str,
    date: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    exp_date: str | None = None,
    strike: float | None = None,
    opt_type: str | None = None,
    minute_type: str | None = None,
    minutes: str | None = None,
) -> pl.DataFrame:
    """Intraday single equity option with raw IV and Greeks."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.EQUITY_INTRADAY_SINGLE_OPTION,
            symbol=symbol,
            date=date,
            from_=from_,
            to=to,
            expDate=exp_date,
            strike=strike,
            optType=opt_type,
            minuteType=minute_type,
            minutes=minutes,
        ),
    )


async def equity_rtdl_options_rawiv(
    client: IVolatilityClient,
    *,
    symbol: str,
    strike_min: float | None = None,
    strike_max: float | None = None,
    exp_min: str | None = None,
    exp_max: str | None = None,
) -> pl.DataFrame:
    """Delayed (20-min) equity options with extended filters."""
    return cast(
        pl.DataFrame,
        await client.fetch(
            Endpoints.EQUITY_RTDL_OPTIONS_RAWIV,
            symbol=symbol,
            strikeMin=strike_min,
            strikeMax=strike_max,
            expMin=exp_min,
            expMax=exp_max,
        ),
    )
