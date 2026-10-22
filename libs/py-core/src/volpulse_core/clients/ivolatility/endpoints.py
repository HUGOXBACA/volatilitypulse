# ─────────────────────────────────────────────────────────────────────────────
# Endpoint definitions for the IVolatility REST API.
#
# Every endpoint the client can call is defined here with its HTTP method,
# path, and the query parameters it accepts. This keeps URL construction in
# one place and makes it trivial to add new endpoints from the OpenAPI spec.
#
# Field name notes:
#   * The upstream parameter ``from`` is a Python keyword; we use ``from_``
#     in Python and rewrite it to ``from`` before sending.
#   * Field names in the proto use camelCase (e.g. ``expFrom``); the client
#     uses snake_case (e.g. ``exp_from``) and rewrites before sending.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Endpoint:
    method: str
    path: str
    params: tuple[str, ...] = ()


class Endpoints:
    # ── Authentication ────────────────────────────────────────────────────
    TOKEN = Endpoint("GET", "/token/get", ("username", "password"))

    # ── Equities: EOD ─────────────────────────────────────────────────────
    EQUITY_STOCK_PRICES = Endpoint(
        "GET", "/equities/eod/stock-prices",
        ("symbol", "date", "from_", "to", "region"),
    )
    EQUITY_OPTIONS_RAWIV = Endpoint(
        "GET", "/equities/eod/stock-opts-by-param",
        ("symbol", "date", "from_", "to", "region", "expFrom", "expTo",
         "strikeFrom", "strikeTo", "callPut", "moneynessFrom", "moneynessTo",
         "deltaFrom", "deltaTo"),
    )
    EQUITY_OPTIONS_NBBO = Endpoint(
        "GET", "/equities/eod/options-nbbo",
        ("symbol", "date", "from_", "to", "region"),
    )
    EQUITY_IVX = Endpoint(
        "GET", "/equities/eod/ivx",
        ("symbol", "date", "from_", "to", "region"),
    )
    EQUITY_IVS = Endpoint(
        "GET", "/equities/eod/ivs",
        ("symbol", "date", "from_", "to", "region"),
    )
    EQUITY_HV = Endpoint(
        "GET", "/equities/eod/hv",
        ("symbol", "date", "from_", "to", "region"),
    )
    EQUITY_OPTION_SERIES = Endpoint(
        "GET", "/equities/eod/option-series",
        ("symbol", "expFrom", "expTo", "strikeFrom", "strikeTo", "callPut"),
    )
    EQUITY_OPTION_SERIES_ON_DATE = Endpoint(
        "GET", "/equities/eod/option-series-on-date",
        ("symbol", "date", "expFrom", "expTo", "strikeFrom", "strikeTo", "callPut"),
    )
    EQUITY_NEAREST_OPTION_TICKERS = Endpoint(
        "GET", "/equities/eod/nearest-option-tickers",
        ("symbol", "startingDate", "dte", "moneyness", "delta", "callPut"),
    )
    EQUITY_NEAREST_OPTION_TICKERS_NBBO = Endpoint(
        "GET", "/equities/eod/nearest-option-tickers-with-prices-nbbo",
        ("symbol", "startingDate", "dte", "moneyness", "delta", "callPut", "region"),
    )
    EQUITY_UNDERLYING_INFO = Endpoint(
        "GET", "/equities/underlying-info",
        ("symbol", "region"),
    )
    EQUITY_YIELD = Endpoint("GET", "/equities/yield", ("symbol",))
    EQUITY_INTEREST_RATES = Endpoint("GET", "/equities/interest-rates", ("from_", "to"))
    EQUITY_IMPLIED_YIELD = Endpoint(
        "GET", "/equities/implied-yield",
        ("symbol", "from_", "to", "region"),
    )
    EQUITY_RT_STOCK_PRICES = Endpoint("GET", "/equities/rt/stock-prices", ("symbol",))
    EQUITY_RT_OPTIONS_RAWIV = Endpoint("GET", "/equities/rt/options-rawiv", ("symbols",))
    EQUITY_DL_OPTIONS_RAWIV = Endpoint(
        "GET", "/equities/dl/options-rawiv",
        ("symbol", "strikeMin", "strikeMax", "expMin", "expMax"),
    )
    EQUITY_RTDL_OPTIONS_RAWIV = Endpoint(
        "GET", "/equities/rtdl/options-rawiv",
        ("symbol", "strikeMin", "strikeMax", "expMin", "expMax"),
    )
    EQUITY_INTRADAY_STOCK_PRICES = Endpoint(
        "GET", "/equities/intraday/stock-prices",
        ("symbol", "date", "from_", "to", "minuteType", "minutes"),
    )
    EQUITY_INTRADAY_OPTIONS_RAWIV = Endpoint(
        "GET", "/equities/intraday/equity-options-rawiv",
        (
            "symbol", "date", "from_", "to", "expDate",
            "strike", "optType", "minuteType", "minutes",
        ),
    )
    EQUITY_INTRADAY_SINGLE_OPTION = Endpoint(
        "GET", "/equities/intraday/single-equity-option-rawiv",
        (
            "symbol", "date", "from_", "to", "expDate",
            "strike", "optType", "minuteType", "minutes",
        ),
    )
    EQUITY_INTRADAY_IVX = Endpoint(
        "GET", "/equities/intraday/ivx",
        ("symbol", "date", "from_", "to", "minuteType", "minutes"),
    )
    EQUITY_INTRADAY_IVS = Endpoint(
        "GET", "/equities/intraday/ivs",
        ("symbol", "date", "from_", "to", "minuteType", "minutes"),
    )
    EQUITY_BREAKING_OUT_IV = Endpoint(
        "GET", "/equities/breaking-out-iv",
        ("symbols", "tradeDate", "period", "terms", "otms", "callPut", "minutes"),
    )
    EQUITY_COLLAPSING_IV = Endpoint(
        "GET", "/equities/collapsing-iv",
        ("symbols", "tradeDate", "period", "terms", "otms", "callPut", "minutes"),
    )
    EQUITY_TOP_STOCKS_BY_VOLUME = Endpoint(
        "GET", "/equities/top-stocks-by-volume",
        ("symbols", "tradeDate", "period", "terms", "otms", "callPut", "minutes"),
    )
    EQUITY_IVX_MEAN_VS_20D_HV = Endpoint(
        "GET", "/equities/ivx-mean-vs-20d-hv",
        ("symbols", "tradeDate", "period", "terms", "otms", "callPut", "minutes"),
    )
    EQUITY_IVX_HISTORICAL_RANGE = Endpoint(
        "GET", "/equities/ivx-historical-range",
        ("symbols", "tradeDate", "period", "terms", "otms", "callPut", "minutes"),
    )
    EQUITY_IVX_VOLATILITY_SKEW = Endpoint(
        "GET", "/equities/ivx-volatility-skew",
        ("symbols", "tradeDate", "period", "terms", "otms", "callPut", "minutes"),
    )
    EQUITY_EARNINGS = Endpoint(
        "GET", "/equities/eod/earnings",
        ("symbols", "from_", "to", "quarter", "strategy", "period"),
    )
    EQUITY_UPCOMING_EARNINGS = Endpoint(
        "GET", "/equities/eod/upcoming-earnings-calendar",
        ("symbols", "from_", "to", "quarter", "strategy", "period"),
    )
    EQUITY_CORP_ACTIONS = Endpoint(
        "GET", "/equities/corp-actions",
        ("symbols", "from_", "to", "quarter", "strategy", "period"),
    )
    EQUITY_STOCK_MARKET_DATA = Endpoint(
        "GET", "/equities/stock-market-data",
        ("symbols", "from_", "to", "quarter", "strategy", "period"),
    )

    # ── Futures ───────────────────────────────────────────────────────────
    FUTURES_PRICES = Endpoint(
        "GET", "/futures/prices", ("rootSymbol", "futureSymbols", "expDate")
    )
    FUTURES_RT_PRICES = Endpoint(
        "GET", "/futures/rt/fut-prices", ("rootSymbol", "futureSymbols", "expDate")
    )
    FUTURES_OPTIONS = Endpoint(
        "GET", "/futures/options", ("futureSymbol", "optExpDate", "moneyness", "optType")
    )
    FUTURES_RT_OPTIONS_RAWIV = Endpoint(
        "GET", "/futures/rt/fut-opt-rawiv",
        ("futureSymbol", "optExpDate", "moneyness", "optType"),
    )
    FUTURES_MARKET_STRUCTURE = Endpoint(
        "GET", "/futures/market-structure", ("futureSymbol",)
    )
    FUTURES_FUT_OPT_MARKET_STRUCTURE = Endpoint(
        "GET", "/futures/fut-opt-market-structure", ("futureSymbol",)
    )
    FUTURES_EOD_PRICES = Endpoint(
        "GET", "/futures/eod/prices", ("symbol", "date", "from_", "to", "region")
    )
    FUTURES_EOD_OPTIONS_RAWIV = Endpoint(
        "GET", "/futures/eod/futures/rawiv", ("symbol", "date", "from_", "to", "region")
    )
    FUTURES_EOD_OPTIONS_NBBO = Endpoint(
        "GET", "/futures/eod/futures/optnbbo", ("symbol", "date", "from_", "to", "region")
    )
    FUTURES_EOD_IVX = Endpoint(
        "GET", "/futures/eod/futures/ivx", ("symbol", "date", "from_", "to", "region")
    )
    FUTURES_EOD_IVS = Endpoint(
        "GET", "/futures/eod/futures/ivs", ("symbol", "date", "from_", "to", "region")
    )
    FUTURES_EOD_HV = Endpoint(
        "GET", "/futures/eod/futures/hv", ("symbol", "date", "from_", "to", "region")
    )
    FUTURES_SINGLE = Endpoint(
        "GET", "/futures/single-futures", ("symbol", "date", "from_", "to", "exchangeCode")
    )
    FUTURES_SINGLE_OPTION = Endpoint(
        "GET", "/futures/single-future-option",
        ("symbol", "date", "from_", "to", "exchangeCode"),
    )
    FUTURES_SINGLE_OPTION_RAWIV = Endpoint(
        "GET", "/futures/single-future-option-rawiv",
        ("symbol", "date", "from_", "to", "exchangeCode"),
    )
    FUTURES_OPTION_SERIES_ON_DATE = Endpoint(
        "GET", "/futures/eod/option-series-on-date",
        ("underlyingSymbol", "date", "expFrom", "expTo", "strikeFrom", "strikeTo", "callPut", "region"),
    )

    # ── Data download (DD) aliases ────────────────────────────────────────
    DD_EQUITY_PRICES = Endpoint(
        "GET", "/dd/eod/equity/prices", ("symbol", "date", "from_", "to", "region")
    )
    DD_EQUITY_RAWIV = Endpoint(
        "GET", "/dd/eod/equity/rawiv", ("symbol", "date", "from_", "to", "region")
    )
    DD_EQUITY_OPTNBB0 = Endpoint(
        "GET", "/dd/eod/equity/optnbbo", ("symbol", "date", "from_", "to", "region")
    )
    DD_EQUITY_IVX = Endpoint(
        "GET", "/dd/eod/equity/ivx", ("symbol", "date", "from_", "to", "region")
    )
    DD_EQUITY_IVS = Endpoint(
        "GET", "/dd/eod/equity/ivs", ("symbol", "date", "from_", "to", "region")
    )
    DD_EQUITY_HV = Endpoint(
        "GET", "/dd/eod/equity/hv", ("symbol", "date", "from_", "to", "region")
    )
    DD_FUTURES_PRICES = Endpoint(
        "GET", "/dd/eod/futures/prices", ("symbol", "date", "from_", "to", "region")
    )
    DD_FUTURES_RAWIV = Endpoint(
        "GET", "/dd/eod/futures/rawiv", ("symbol", "date", "from_", "to", "region")
    )
    DD_FUTURES_OPTNBB0 = Endpoint(
        "GET", "/dd/eod/futures/optnbbo", ("symbol", "date", "from_", "to", "region")
    )
    DD_FUTURES_IVX = Endpoint(
        "GET", "/dd/eod/futures/ivx", ("symbol", "date", "from_", "to", "region")
    )
    DD_FUTURES_IVS = Endpoint(
        "GET", "/dd/eod/futures/ivs", ("symbol", "date", "from_", "to", "region")
    )
    DD_FUTURES_HV = Endpoint(
        "GET", "/dd/eod/futures/hv", ("symbol", "date", "from_", "to", "region")
    )
