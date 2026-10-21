"""Artefact persistence: Parquet and NPZ."""

from __future__ import annotations

from volpulse_core.io.parquet import read_npz, read_parquet, write_npz, write_parquet

__all__ = ["read_npz", "read_parquet", "write_npz", "write_parquet"]
