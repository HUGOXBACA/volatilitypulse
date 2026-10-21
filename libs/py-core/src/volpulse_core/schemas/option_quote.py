"""Pandera schemas validating everything that enters the pipeline.

Upstream payloads are validated at the boundary, before they reach the
analytics code. A structurally corrupt payload must fail loudly at the edge
rather than silently poison the surfaces and Greeks computed from it.
"""

from __future__ import annotations

import pandera.pandas as pa
from pandera.typing import Series

__all__ = ["option_quote_schema"]


option_quote_schema = pa.DataFrameSchema(
    {
        "contract_id": pa.Column(str, nullable=False),
        "underlying_symbol": pa.Column(str, nullable=False),
        "expiry_epoch_day": pa.Column("int64", nullable=False, coerce=True),
        "strike": pa.Column(float, nullable=False, coerce=True, checks=pa.Check.gt(0.0)),
        "right": pa.Column(
            str,
            nullable=False,
            coerce=True,
            checks=pa.Check.isin(["CALL", "PUT"]),
        ),
        "bid": pa.Column(float, nullable=False, coerce=True, checks=pa.Check.ge(0.0)),
        "ask": pa.Column(float, nullable=False, coerce=True, checks=pa.Check.ge(0.0)),
        "last": pa.Column(float, nullable=False, coerce=True, checks=pa.Check.ge(0.0)),
        "close": pa.Column(float, nullable=False, coerce=True, checks=pa.Check.ge(0.0)),
        "implied_volatility": pa.Column(
            float,
            nullable=True,
            coerce=True,
            checks=pa.Check.in_range(0.0, 10.0),
        ),
        "event_time_ns": pa.Column("int64", nullable=False, coerce=True),
        "ingest_time_ns": pa.Column("int64", nullable=False, coerce=True),
        "sequence": pa.Column("int64", nullable=False, coerce=True),
    },
    # The upstream adds fields over time; unknown columns must not break the
    # consumer, but the columns we depend on are always checked.
    strict=False,
    coerce=True,
    checks=[
        pa.Check(
            lambda frame: ~(frame["bid"].gt(0.0) & frame["ask"].gt(0.0) & frame["bid"].gt(frame["ask"])),
            error="crossed market: bid above ask",
        ),
    ],
)
