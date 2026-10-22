"""Tests for the IVolatility REST client.

Uses real data files from IVolatility to test data loading and parsing.
No network calls are made - all data comes from local files.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

TEST_DATA_DIR = Path(__file__).parent / "data"

GARCH_USDJPY = TEST_DATA_DIR / "garch_usdjpy.csv"
FUTURES_OPTS_2024 = TEST_DATA_DIR / "futures_opts_2024.csv"
IVOL_OEX_2016_2019 = TEST_DATA_DIR / "ivol_oex_2016_2019.npz"
IVOL_RATES_2016_2026 = TEST_DATA_DIR / "ivol_rates_2016_2026.npz"

# ── GARCH data tests ─────────────────────────────────────────────────────────


def test_garch_csv_has_valid_structure() -> None:
    """GARCH CSV should have two columns: date and volatility value."""
    df = pl.read_csv(GARCH_USDJPY, has_header=True)
    assert df.shape[0] > 0
    assert df.shape[1] == 2
    # First column has no header (empty string), second is the vol name
    assert df.columns[1] == "US Dollar to Japanese Yen - GARCH Volatility"
    # All vol values should be positive floats < 1.0 (IV < 100%)
    vol_col = df.columns[1]
    vols = df[vol_col].drop_nulls()
    vols_list = [float(v) for v in vols.to_list()]
    assert min(vols_list) > 0
    assert max(vols_list) < 1.0


def test_garch_csv_date_range() -> None:
    """GARCH data should span a reasonable date range."""
    df = pl.read_csv(GARCH_USDJPY, has_header=True)
    # First column is the date column (no header name)
    date_col = df.columns[0]
    dates = df[date_col]
    assert str(dates.min()) >= "2016-01-01"
    assert str(dates.max()) <= "2026-12-31"


# ── Futures options CSV tests ────────────────────────────────────────────────

def test_futures_options_csv_has_valid_structure() -> None:
    """Futures options CSV should have expected columns."""
    df = pl.read_csv(FUTURES_OPTS_2024)
    assert df.shape[0] > 0
    expected_cols = [
        "trade_date", "opt_symbol", "dte", "futSymbol", "expiration_date",
        "call_put", "strike", "price_open", "price_high", "price_low", "price",
        "volume", "openinterest", "iv", "delta", "iv_interpolated", "gamma",
        "theta", "vega", "ask", "bid", "underlying_price", "calc_OTM",
        "settle", "target_symbol", "tenor_bucket", "smile_node",
    ]
    for col in expected_cols:
        assert col in df.columns, f"Missing column: {col}"


def test_futures_options_has_valid_iv() -> None:
    """Implied volatility should be positive and reasonable (< 500%).
    Some quotes may have iv=-1 meaning no valid IV, filter those out."""
    df = pl.read_csv(FUTURES_OPTS_2024)
    iv_col = df["iv"]
    valid_iv = [float(v) for v in iv_col.drop_nulls().to_list() if v is not None and float(v) > 0]
    assert len(valid_iv) > 0
    assert min(valid_iv) > 0
    assert max(valid_iv) < 5.0  # IV < 500%


def test_futures_options_has_valid_strikes() -> None:
    """Strike prices should be positive."""
    df = pl.read_csv(FUTURES_OPTS_2024)
    strikes = df["strike"].drop_nulls()
    strikes_list = [float(s) for s in strikes.to_list()]
    assert min(strikes_list) > 0
    assert max(strikes_list) < 10000  # Reasonable upper bound


# ── NPZ data tests ───────────────────────────────────────────────────────────


def test_npz_oex_has_valid_structure() -> None:
    """OEX NPZ should have data, columns, and index arrays."""
    npz = np.load(IVOL_OEX_2016_2019, allow_pickle=True)
    assert "data" in npz.files
    assert "columns" in npz.files
    assert "index" in npz.files
    data = npz["data"]
    assert data.shape[0] > 0
    assert data.shape[1] == 13


def test_npz_oex_columns_match_expected() -> None:
    """OEX NPZ columns should match expected schema."""
    npz = np.load(IVOL_OEX_2016_2019, allow_pickle=True)
    expected_cols = [
        "record_no", "symbol", "exchange", "date", "price",
        "10d HV", "20d HV", "30d HV", "60d HV", "90d HV",
        "120d HV", "150d HV", "180d HV",
    ]
    assert list(npz["columns"]) == expected_cols


def test_npz_oex_has_valid_data() -> None:
    """OEX NPZ data should have valid prices and IV values."""
    npz = np.load(IVOL_OEX_2016_2019, allow_pickle=True)
    data = npz["data"]
    prices = data[:, 4]  # price column
    valid_prices = [p for p in prices if p is not None and str(p) != "nan"]
    assert len(valid_prices) > 0
    assert min(float(p) for p in valid_prices) > 0
    assert max(float(p) for p in valid_prices) < 100000

    # Check HV values are positive
    hv_10d = data[:, 5]  # 10d HV column
    valid_hv = [h for h in hv_10d if h is not None and str(h) != "nan"]
    assert len(valid_hv) > 0
    assert min(float(h) for h in valid_hv) > 0
    assert max(float(h) for h in valid_hv) < 5.0  # HV < 500%


def test_npz_rates_has_valid_structure() -> None:
    """Interest rate NPZ should have data, columns, and index arrays."""
    npz = np.load(IVOL_RATES_2016_2026, allow_pickle=True)
    assert "data" in npz.files
    assert "columns" in npz.files
    assert "index" in npz.files
    data = npz["data"]
    assert data.shape[0] > 0
    assert data.shape[1] == 4


def test_npz_rates_columns_match_expected() -> None:
    """Interest rate NPZ columns should match expected schema."""
    npz = np.load(IVOL_RATES_2016_2026, allow_pickle=True)
    expected_cols = ["t_date", "period", "currency", "rate"]
    assert list(npz["columns"]) == expected_cols


def test_npz_rates_has_valid_data() -> None:
    """Interest rate data should have valid rates."""
    npz = np.load(IVOL_RATES_2016_2026, allow_pickle=True)
    data = npz["data"]
    rates = data[:, 3]  # rate column
    valid_rates = [r for r in rates if r is not None and str(r) != "nan"]
    assert len(valid_rates) > 0
    assert min(float(r) for r in valid_rates) >= 0
    # Interest rates can exceed 100% (e.g. 8.79%), use a generous upper bound
    assert max(float(r) for r in valid_rates) < 50.0


# ── Cross-reference tests ────────────────────────────────────────────────────

def test_multiple_npz_files_have_consistent_schema() -> None:
    """Both OEX NPZ files should have the same column structure."""
    npz1 = np.load(IVOL_OEX_2016_2019, allow_pickle=True)
    npz2 = np.load(
        "/Users/user0001/Projects/independentresearch/brownianmotion/data/"
        "ivol_OEX_historical_volatility_2020-01-01_to_2026-09-30.npz",
        allow_pickle=True,
    )
    assert list(npz1["columns"]) == list(npz2["columns"])
    assert npz1["data"].shape[1] == npz2["data"].shape[1]


def test_data_files_exist() -> None:
    """All test data files should exist."""
    for f in [GARCH_USDJPY, FUTURES_OPTS_2024, IVOL_OEX_2016_2019, IVOL_RATES_2016_2026]:
        assert f.exists(), f"Missing test data file: {f}"
        assert f.stat().st_size > 0, f"Empty test data file: {f}"
