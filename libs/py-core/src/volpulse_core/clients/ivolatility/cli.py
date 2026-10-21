# ─────────────────────────────────────────────────────────────────────────────
# Command-line interface for the IVolatility data puller.
#
#   volpulse-fetch equity stock-prices --symbol AAPL --from 2024-01-01 --to 2024-01-31
#   volpulse-fetch futures prices --symbol ES --from 2024-01-01 --to 2024-01-31
#   volpulse-fetch auth token --username ... --password ...
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import polars as pl

from volpulse_core.clients.ivolatility import (
    IVolatilityClient,
    IVolatilitySettings,
)
from volpulse_core.clients.ivolatility.equity import (
    equity_hv,
    equity_interest_rates,
    equity_ivs,
    equity_ivx,
    equity_nearest_option_tickers,
    equity_option_series,
    equity_options_rawiv,
    equity_rt_options_rawiv,
    equity_rt_stock_prices,
    equity_rtdl_options_rawiv,
    equity_stock_prices,
    equity_underlying_info,
    equity_yield,
)
from volpulse_core.clients.ivolatility.futures import (
    futures_eod_hv,
    futures_eod_ivs,
    futures_eod_ivx,
    futures_eod_options_rawiv,
    futures_eod_prices,
    futures_options,
    futures_prices,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="volpulse-fetch",
        description="Pull data from the IVolatility REST API.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override the API base URL (env: IVOL_BASE_URL).",
    )
    parser.add_argument(
        "--username",
        default=None,
        help="IVolatility username (env: IVOL_USERNAME).",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="IVolatility password (env: IVOL_PASSWORD).",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Write result to this file (parquet/json/csv). Defaults to stdout.",
    )
    parser.add_argument(
        "--format",
        default="parquet",
        choices=["parquet", "json", "csv"],
        help="Output format (default: parquet).",
    )
    parser.add_argument(
        "--rate-limit-rps",
        type=float,
        default=None,
        help="Max requests per second (env: IVOL_RATE_LIMIT_RPS, default 1.0).",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ── auth ──────────────────────────────────────────────────────────────
    auth = sub.add_parser("auth", help="Authentication helpers")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_token = auth_sub.add_parser("token", help="Obtain an IVolatility bearer token")
    auth_token.add_argument("--username", required=True)
    auth_token.add_argument("--password", required=True)

    # ── equity ────────────────────────────────────────────────────────────
    eq_p = sub.add_parser("equity", help="Equity endpoints")
    eq_sub = eq_p.add_subparsers(dest="eq_command", required=True)

    def add_common_date_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--date", help="Single trading date (yyyy-mm-dd)")
        p.add_argument("--from", dest="from_", help="Start date (yyyy-mm-dd)")
        p.add_argument("--to", help="End date (yyyy-mm-dd)")
        p.add_argument("--region", default="USA", help="Region (default USA)")

    p = eq_sub.add_parser("stock-prices", help="EOD equity prices")
    p.add_argument("--symbol", required=True)
    add_common_date_args(p)

    p = eq_sub.add_parser("options-rawiv", help="EOD options raw IV & Greeks")
    p.add_argument("--symbol", required=True)
    add_common_date_args(p)

    p = eq_sub.add_parser("ivx", help="EOD IVX")
    p.add_argument("--symbol", required=True)
    add_common_date_args(p)

    p = eq_sub.add_parser("ivs", help="EOD IV surface")
    p.add_argument("--symbol", required=True)
    add_common_date_args(p)

    p = eq_sub.add_parser("hv", help="EOD historical volatility")
    p.add_argument("--symbol", required=True)
    add_common_date_args(p)

    p = eq_sub.add_parser("option-series", help="EOD option series metadata")
    p.add_argument("--symbol", required=True)
    p.add_argument("--exp-from")
    p.add_argument("--exp-to")
    p.add_argument("--strike-from", type=float)
    p.add_argument("--strike-to", type=float)
    p.add_argument("--call-put", choices=["C", "P"])

    p = eq_sub.add_parser("nearest-option-tickers", help="Nearest option tickers")
    p.add_argument("--symbol", required=True)
    p.add_argument("--dte", type=int, required=True)
    p.add_argument("--starting-date")
    p.add_argument("--moneyness", type=int)
    p.add_argument("--delta", type=float)
    p.add_argument("--call-put", choices=["C", "P"])

    p = eq_sub.add_parser("underlying-info", help="Equity reference info")
    p.add_argument("--symbol", required=True)
    p.add_argument("--region", default="USA")

    p = eq_sub.add_parser("yield", help="12-month average dividend yield")
    p.add_argument("--symbol", required=True)

    p = eq_sub.add_parser("interest-rates", help="Interpolated interest rates")
    p.add_argument("--from", dest="from_", required=True)
    p.add_argument("--to", required=True)

    p = eq_sub.add_parser("rt-stock-prices", help="Realtime equity prices")
    p.add_argument("--symbol", required=True)

    p = eq_sub.add_parser("rt-options-rawiv", help="Realtime options raw IV")
    p.add_argument("--symbols", required=True, help="Comma-separated option symbols")

    p = eq_sub.add_parser("rtdl-options-rawiv", help="Delayed options raw IV")
    p.add_argument("--symbol", required=True)
    p.add_argument("--strike-min", type=float)
    p.add_argument("--strike-max", type=float)
    p.add_argument("--exp-min")
    p.add_argument("--exp-max")

    # ── futures ───────────────────────────────────────────────────────────
    fu_p = sub.add_parser("futures", help="Futures endpoints")
    fu_sub = fu_p.add_subparsers(dest="fu_command", required=True)

    p = fu_sub.add_parser("prices", help="Realtime futures prices")
    p.add_argument("--root-symbol")
    p.add_argument("--future-symbols")
    p.add_argument("--exp-date")

    p = fu_sub.add_parser("options", help="Realtime futures options chain")
    p.add_argument("--future-symbol", required=True)
    p.add_argument("--opt-exp-date")
    p.add_argument("--moneyness", required=True)
    p.add_argument("--opt-type", choices=["CALL", "PUT", "ALL"])

    p = fu_sub.add_parser("eod-prices", help="EOD futures prices")
    p.add_argument("--symbol", required=True)
    add_common_date_args(p)

    p = fu_sub.add_parser("eod-options-rawiv", help="EOD futures options raw IV")
    p.add_argument("--symbol", required=True)
    add_common_date_args(p)

    p = fu_sub.add_parser("eod-ivx", help="EOD futures IVX")
    p.add_argument("--symbol", required=True)
    add_common_date_args(p)

    p = fu_sub.add_parser("eod-ivs", help="EOD futures IV surface")
    p.add_argument("--symbol", required=True)
    add_common_date_args(p)

    p = fu_sub.add_parser("eod-hv", help="EOD futures historical volatility")
    p.add_argument("--symbol", required=True)
    add_common_date_args(p)

    return parser


async def run(args: argparse.Namespace) -> int:
    settings = IVolatilitySettings()
    if args.base_url is not None:
        settings.base_url = args.base_url
    if args.username is not None:
        settings.username = args.username
    if args.password is not None:
        settings.password = args.password
    if args.rate_limit_rps is not None:
        settings.rate_limit_rps = args.rate_limit_rps

    async with IVolatilityClient(settings) as client:
        df: pl.DataFrame

        if args.command == "auth":
            # Auth is handled inside the client; just verify we can get a token.
            token = await client.get_token()
            print(token)
            return 0

        cmd = args.eq_command if args.command == "equity" else args.fu_command

        # ── equity dispatch ─────────────────────────────────────────────
        if args.command == "equity":
            if cmd == "stock-prices":
                df = await equity_stock_prices(
                    client,
                    symbol=args.symbol,
                    date=args.date,
                    from_=args.from_,
                    to=args.to,
                    region=args.region,
                )
            elif cmd == "options-rawiv":
                df = await equity_options_rawiv(
                    client,
                    symbol=args.symbol,
                    date=args.date,
                    from_=args.from_,
                    to=args.to,
                    region=args.region,
                )
            elif cmd == "ivx":
                df = await equity_ivx(
                    client,
                    symbol=args.symbol,
                    date=args.date,
                    from_=args.from_,
                    to=args.to,
                    region=args.region,
                )
            elif cmd == "ivs":
                df = await equity_ivs(
                    client,
                    symbol=args.symbol,
                    date=args.date,
                    from_=args.from_,
                    to=args.to,
                    region=args.region,
                )
            elif cmd == "hv":
                df = await equity_hv(
                    client,
                    symbol=args.symbol,
                    date=args.date,
                    from_=args.from_,
                    to=args.to,
                    region=args.region,
                )
            elif cmd == "option-series":
                df = await equity_option_series(
                    client,
                    symbol=args.symbol,
                    exp_from=args.exp_from,
                    exp_to=args.exp_to,
                    strike_from=args.strike_from,
                    strike_to=args.strike_to,
                    call_put=args.call_put,
                )
            elif cmd == "nearest-option-tickers":
                df = await equity_nearest_option_tickers(
                    client,
                    symbol=args.symbol,
                    dte=args.dte,
                    starting_date=args.starting_date,
                    moneyness=args.moneyness,
                    delta=args.delta,
                    call_put=args.call_put,
                )
            elif cmd == "underlying-info":
                df = await equity_underlying_info(
                    client,
                    symbol=args.symbol,
                    region=args.region,
                )
            elif cmd == "yield":
                df = await equity_yield(client, symbol=args.symbol)
            elif cmd == "interest-rates":
                df = await equity_interest_rates(
                    client,
                    from_=args.from_,
                    to=args.to,
                )
            elif cmd == "rt-stock-prices":
                df = await equity_rt_stock_prices(client, symbol=args.symbol)
            elif cmd == "rt-options-rawiv":
                df = await equity_rt_options_rawiv(client, symbols=args.symbols)
            elif cmd == "rtdl-options-rawiv":
                df = await equity_rtdl_options_rawiv(
                    client,
                    symbol=args.symbol,
                    strike_min=args.strike_min,
                    strike_max=args.strike_max,
                    exp_min=args.exp_min,
                    exp_max=args.exp_max,
                )
            else:  # pragma: no cover - argparse enforces
                raise SystemExit(f"unknown equity command: {cmd}")

        # ── futures dispatch ────────────────────────────────────────────
        elif cmd == "prices":
            df = await futures_prices(
                client,
                root_symbol=args.root_symbol,
                future_symbols=args.future_symbols,
                exp_date=args.exp_date,
            )
        elif cmd == "options":
            df = await futures_options(
                client,
                future_symbol=args.future_symbol,
                opt_exp_date=args.opt_exp_date,
                moneyness=args.moneyness,
                opt_type=args.opt_type,
            )
        elif cmd == "eod-prices":
            df = await futures_eod_prices(
                client,
                symbol=args.symbol,
                date=args.date,
                from_=args.from_,
                to=args.to,
                region=args.region,
            )
        elif cmd == "eod-options-rawiv":
            df = await futures_eod_options_rawiv(
                client,
                symbol=args.symbol,
                date=args.date,
                from_=args.from_,
                to=args.to,
                region=args.region,
            )
        elif cmd == "eod-ivx":
            df = await futures_eod_ivx(
                client,
                symbol=args.symbol,
                date=args.date,
                from_=args.from_,
                to=args.to,
                region=args.region,
            )
        elif cmd == "eod-ivs":
            df = await futures_eod_ivs(
                client,
                symbol=args.symbol,
                date=args.date,
                from_=args.from_,
                to=args.to,
                region=args.region,
            )
        elif cmd == "eod-hv":
            df = await futures_eod_hv(
                client,
                symbol=args.symbol,
                date=args.date,
                from_=args.from_,
                to=args.to,
                region=args.region,
            )
        else:  # pragma: no cover - argparse enforces
            raise SystemExit(f"unknown futures command: {cmd}")

    # ── Output ──────────────────────────────────────────────────────────
    if args.format == "json":
        text = df.write_json()
    elif args.format == "csv":
        text = df.write_csv()
    else:
        df.write_parquet(args.output or sys.stdout.buffer)
        return 0

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
