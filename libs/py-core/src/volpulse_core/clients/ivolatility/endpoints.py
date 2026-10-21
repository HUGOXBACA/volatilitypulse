# ─────────────────────────────────────────────────────────────────────────────
# Endpoint definitions.
#
# Every endpoint the client can call is declared here with its HTTP method,
# path, and the query parameters it accepts. This keeps the URL construction
# in one place and makes it trivial to add new endpoints from the OpenAPI spec.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Endpoint:
    method: str
    path: str
    # Parameter names accepted by this endpoint, in the order they should be
    # documented. ``"from"`` is reserved upstream; clients must use ``from_``
    # and the client rewrites it before sending.
    params: tuple[str, ...] = ()


class Endpoints:
    # ── Authentication ────────────────────────────────────────────────────
    TOKEN = Endpoint("GET", "/token/get", ("username", "password"))

    # ── Equities ──────────────────────────────────────────────────────────
    EQUITY_STOCK_PRICES = Endpoint(
        "GET",
        "/equities/eod/stock-prices",
        ("symbol", "date", "from_", "to", "region"),
    )
    EQUITY_OPTIONS_RAWIV = Endpoint(
        "GET",
        "/equities/eod/options-rawiv",
        ("symbol", "date", "from_", "to", "region"),
    )
    EQUITY_OPTIONS_NBBO = Endpoint(
        "GET",
        "/equities/eod/options-nbbo",
        ("symbol", "date", "from_", "to", "region"),
    )
    EQUITY_IVX = Endpoint(
        "GET",
        "/equities/eod/ivx",
        ("symbol", "date", "from_", "to", "region"),
    )
    EQUITY_IVS = Endpoint(
        "GET",
        "/equities/eod/ivs",
        ("symbol", "date", "from_", "to", "region"),
    )
    EQUITY_HV = Endpoint(
        "GET",
        "/equities/eod/hv",
        ("symbol", "date", "from_", "to", "region"),
    )
    EQUITY_OPTION_SERIES = Endpoint(
        "GET",
        "/equities/eod/option-series",
        ("symbol", "expFrom", "expTo", "strikeFrom", "strikeTo", "callPut"),
    )
    EQUITY_NEAREST_OPTION_TICKERS = Endpoint(
        "GET",
        "/equities/eod/nearest-option-tickers",
        ("symbol", "startingDate", "dte", "moneyness", "delta", "callPut"),
    )
    EQUITY_UNDERLYING_INFO = Endpoint(
        "GET",
        "/equities/underlying-info",
        ("symbol", "region"),
    )
    EQUITY_YIELD = Endpoint("GET", "/equities/yield", ("symbol",))
    EQUITY_INTEREST_RATES = Endpoint("GET", "/equities/interest-rates", ("from_", "to"))
    EQUITY_RT_STOCK_PRICES = Endpoint("GET", "/equities/rt/stock-prices", ("symbol",))
    EQUITY_RT_OPTIONS_RAWIV = Endpoint(
        "GET", "/equities/rt/options-rawiv", ("symbols",)
    )
    EQUITY_INTRADAY_STOCK_PRICES = Endpoint(
        "GET",
        "/equities/intraday/stock-prices",
        ("symbol", "date", "from_", "to", "minuteType", "minutes"),
    )
    EQUITY_INTRADAY_OPTIONS = Endpoint(
        "GET",
        "/equities/intraday/equity-options-rawiv",
        (
            "symbol",
            "date",
            "from_",
            "to",
            "expDate",
            "strike",
            "optType",
            "minuteType",
            "minutes",
        ),
    )
    EQUITY_INTRADAY_SINGLE_OPTION = Endpoint(
        "GET",
        "/equities/intraday/single-equity-option-rawiv",
        (
            "symbol",
            "date",
            "from_",
            "to",
            "expDate",
            "strike",
            "optType",
            "minuteType",
            "minutes",
        ),
    )
    EQUITY_RTDL_OPTIONS_RAWIV = Endpoint(
        "GET",
        "/equities/rtdl/options-rawiv",
        ("symbol", "strikeMin", "strikeMax", "expMin", "expMax"),
    )

    # ── Futures ───────────────────────────────────────────────────────────
    FUTURES_PRICES = Endpoint(
        "GET", "/futures/prices", ("rootSymbol", "futureSymbols", "expDate")
    )
    FUTURES_RT_PRICES = Endpoint(
        "GET", "/futures/rt/fut-prices", ("rootSymbol", "futureSymbols", "expDate")
    )
    FUTURES_OPTIONS = Endpoint(
        "GET",
        "/futures/options",
        ("futureSymbol", "optExpDate", "moneyness", "optType"),
    )
    FUTURES_RT_OPTIONS_RAWIV = Endpoint(
        "GET",
        "/futures/rt/fut-opt-rawiv",
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
        "GET", "/futures/eod/options-rawiv", ("symbol", "date", "from_", "to", "region")
    )
    FUTURES_EOD_OPTIONS_NBBO = Endpoint(
        "GET", "/futures/eod/options-nbbo", ("symbol", "date", "from_", "to", "region")
    )
    FUTURES_EOD_IVX = Endpoint(
        "GET", "/futures/eod/ivx", ("symbol", "date", "from_", "to", "region")
    )
    FUTURES_EOD_IVS = Endpoint(
        "GET", "/futures/eod/ivs", ("symbol", "date", "from_", "to", "region")
    )
    FUTURES_EOD_HV = Endpoint(
        "GET", "/futures/eod/hv", ("symbol", "date", "from_", "to", "region")
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
