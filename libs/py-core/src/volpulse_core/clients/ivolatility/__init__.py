# ─────────────────────────────────────────────────────────────────────────────
# IVolatility API client package.
#
#   from volpulse_core.clients.ivolatility import IVolatilityClient, Endpoints
#   async with IVolatilityClient() as client:
#       df = await client.fetch(Endpoints.EQUITY_STOCK_PRICES, symbol="AAPL",
#                               from_="2024-01-01", to="2024-01-31")
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from volpulse_core.clients.ivolatility.auth import IVolatilityAuth
from volpulse_core.clients.ivolatility.client import IVolatilityClient
from volpulse_core.clients.ivolatility.config import IVolatilitySettings
from volpulse_core.clients.ivolatility.endpoints import Endpoint, Endpoints
from volpulse_core.clients.ivolatility.equity import (
    equity_hv,
    equity_interest_rates,
    equity_intraday_options_rawiv,
    equity_intraday_stock_prices,
    equity_ivs,
    equity_ivx,
    equity_nearest_option_tickers,
    equity_option_series,
    equity_options_nbbo,
    equity_options_rawiv,
    equity_rt_options_rawiv,
    equity_rt_stock_prices,
    equity_rtdl_options_rawiv,
    equity_stock_prices,
    equity_underlying_info,
    equity_yield,
)
from volpulse_core.clients.ivolatility.exceptions import (
    IVolatilityAPIError,
    IVolatilityAuthError,
    IVolatilityError,
    IVolatilityPendingError,
    IVolatilityRateLimitError,
)
from volpulse_core.clients.ivolatility.futures import (
    futures_eod_hv,
    futures_eod_ivs,
    futures_eod_ivx,
    futures_eod_options_nbbo,
    futures_eod_options_rawiv,
    futures_eod_prices,
    futures_fut_opt_market_structure,
    futures_market_structure,
    futures_options,
    futures_prices,
    futures_rt_options_rawiv,
    futures_rt_prices,
)
from volpulse_core.clients.ivolatility.models import APIResponse, Query, Status

__all__ = [
    "APIResponse",
    "Endpoint",
    "Endpoints",
    "IVolatilityAPIError",
    "IVolatilityAuth",
    "IVolatilityAuthError",
    "IVolatilityClient",
    "IVolatilityError",
    "IVolatilityPendingError",
    "IVolatilityRateLimitError",
    "IVolatilitySettings",
    "Query",
    "Status",
    "equity_hv",
    "equity_interest_rates",
    "equity_intraday_options_rawiv",
    "equity_intraday_stock_prices",
    "equity_ivs",
    "equity_ivx",
    "equity_nearest_option_tickers",
    "equity_option_series",
    "equity_options_nbbo",
    "equity_options_rawiv",
    "equity_rt_options_rawiv",
    "equity_rt_stock_prices",
    "equity_rtdl_options_rawiv",
    "equity_stock_prices",
    "equity_underlying_info",
    "equity_yield",
    "futures_eod_hv",
    "futures_eod_ivs",
    "futures_eod_ivx",
    "futures_eod_options_nbbo",
    "futures_eod_options_rawiv",
    "futures_eod_prices",
    "futures_fut_opt_market_structure",
    "futures_market_structure",
    "futures_options",
    "futures_prices",
    "futures_rt_options_rawiv",
    "futures_rt_prices",
]
