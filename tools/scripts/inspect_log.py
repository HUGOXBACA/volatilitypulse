#!/usr/bin/env python3
"""Inspect a VolPulse binary audit log.

The log is the pipeline's audit trail: everything the ingestion engine
produced, in order, with a CRC-32 per record. This tool decodes it without
the C++ library, so the log can be inspected with nothing but Python.

    python tools/scripts/inspect_log.py var/binary-logs/options.vlog
    python tools/scripts/inspect_log.py var/binary-logs/options.vlog --quotes 10

The on-disk format is documented in
``libs/cpp-core/include/volpulse/binarylog/format.h`` and the payload
layout in ``services/ingestion-cpp/include/volpulse/ingestion/quote_codec.h``.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

# ── Record header (32 bytes, little endian) ────────────────────────────────
# magic | version | flags | payload_size | sequence | timestamp_ns | crc32
HEADER = struct.Struct("<IHHIqqI")
HEADER_SIZE = 32
MAGIC = 0x534C5056  # 'VPLS'
VERSION = 1
ALIGNMENT = 8

# ── Quote payload (104 bytes, little endian) ───────────────────────────────
# magic | version | reserved | timestamp_ns | strike | bid | ask | last | iv
#       | contract_id[32] | underlying_symbol[16]
QUOTE = struct.Struct("<IHHqddddd32s16s")
QUOTE_SIZE = 104
QUOTE_MAGIC = 0x30505156  # 'VPQ0'


@dataclass(frozen=True, slots=True)
class Record:
    """One decoded record."""

    sequence: int
    timestamp_ns: int
    payload: bytes


def scan(data: bytes) -> tuple[list[Record], int, bool]:
    """Walk a log file.

    Args:
        data: The whole file.

    Returns:
        The records, the offset just past the last valid record, and whether
        a torn or corrupt tail was found.
    """
    records: list[Record] = []
    offset = 0

    while offset + HEADER_SIZE <= len(data):
        magic, version, _flags, payload_size, sequence, timestamp_ns, crc = HEADER.unpack_from(
            data, offset
        )
        if magic != MAGIC or version != VERSION:
            break

        padded = (payload_size + ALIGNMENT - 1) & ~(ALIGNMENT - 1)
        if offset + HEADER_SIZE + padded > len(data):
            break

        payload = data[offset + HEADER_SIZE : offset + HEADER_SIZE + payload_size]
        if zlib.crc32(payload) & 0xFFFFFFFF != crc:
            break

        records.append(Record(sequence=sequence, timestamp_ns=timestamp_ns, payload=payload))
        offset += HEADER_SIZE + padded

    tail = data[offset:]
    # A tail of zero bytes is the unused capacity of the writer's mapping,
    # not damage. Anything else is a torn or corrupt tail.
    truncated = bool(tail) and any(tail)
    return records, offset, truncated


def decode_quote(payload: bytes) -> dict[str, object] | None:
    """Decode a quote payload, if that is what it is."""
    if len(payload) < QUOTE_SIZE:
        return None
    (
        magic,
        _version,
        _reserved,
        timestamp_ns,
        strike,
        bid,
        ask,
        last,
        implied_volatility,
        contract_id,
        underlying_symbol,
    ) = QUOTE.unpack_from(payload)
    if magic != QUOTE_MAGIC:
        return None
    return {
        "contract_id": contract_id.split(b"\x00", 1)[0].decode("utf-8", "replace"),
        "underlying_symbol": underlying_symbol.split(b"\x00", 1)[0].decode("utf-8", "replace"),
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "last": last,
        "implied_volatility": implied_volatility,
        "timestamp_ns": timestamp_ns,
    }


def main() -> int:
    """Inspect the log given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="The binary log to inspect.")
    parser.add_argument(
        "--quotes",
        type=int,
        default=10,
        help="How many quotes to print (default: 10).",
    )
    args = parser.parse_args()

    if not args.path.exists():
        print(f"inspect-log: {args.path} does not exist", file=sys.stderr)
        return 1

    data = args.path.read_bytes()
    records, valid_end, truncated = scan(data)

    print(f"file        : {args.path}")
    print(f"size        : {len(data):,} bytes")
    print(f"records     : {len(records):,}")
    print(f"valid bytes : {valid_end:,}")
    if truncated:
        print("tail        : TORN OR CORRUPT (the writer will heal it on the next open)")
    else:
        print("tail        : clean")

    if records:
        print(f"sequence    : {records[0].sequence}..{records[-1].sequence}")
        span_ns = records[-1].timestamp_ns - records[0].timestamp_ns
        print(f"time span   : {span_ns / 1e9:.3f}s")

        quotes = [q for q in (decode_quote(r.payload) for r in records) if q is not None]
        if quotes:
            symbols = sorted({str(q["underlying_symbol"]) for q in quotes})
            print(f"symbols     : {', '.join(symbols)}")
            strikes = [float(q["strike"]) for q in quotes]
            print(f"strike range: {min(strikes):.2f} .. {max(strikes):.2f}")

            if args.quotes:
                print(f"\nfirst {min(args.quotes, len(quotes))} quotes:")
                for quote in quotes[: args.quotes]:
                    print(
                        f"  {quote['underlying_symbol']:6s} "
                        f"{quote['contract_id']:20s} "
                        f"K={float(quote['strike']):8.2f} "
                        f"bid={float(quote['bid']):6.2f} "
                        f"ask={float(quote['ask']):6.2f} "
                        f"iv={float(quote['implied_volatility']):.4f}"
                    )

    return 0 if not truncated else 2


if __name__ == "__main__":
    raise SystemExit(main())
