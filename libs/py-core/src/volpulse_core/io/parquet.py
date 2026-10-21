"""Persistence of heavy analytics artefacts.

Parquet for columnar time series, NPZ for compressed numeric arrays. Writes
are atomic: the data is written to a temporary file in the same directory and
then renamed, so a crash can never leave a half-written artefact behind.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import polars as pl

__all__ = ["read_npz", "read_parquet", "write_npz", "write_parquet"]


def write_parquet(
    frame: pl.DataFrame,
    path: Path,
    *,
    compression: str = "zstd",
) -> Path:
    """Write a Polars frame to Parquet, atomically.

    Args:
        frame: Frame to persist.
        path: Destination path. Parent directories are created.
        compression: Parquet compression codec.

    Returns:
        The path that was written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".parquet.tmp")
    os.close(handle)
    try:
        frame.write_parquet(temporary, compression=compression)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


def read_parquet(path: Path) -> pl.DataFrame:
    """Read a Parquet artefact into a Polars frame."""
    return pl.read_parquet(Path(path))


def write_npz(path: Path, **arrays: np.ndarray) -> Path:
    """Write compressed NumPy arrays to an NPZ archive, atomically.

    Args:
        path: Destination path. Parent directories are created.
        **arrays: Named arrays to store.

    Returns:
        The path that was written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".npz.tmp")
    os.close(handle)
    try:
        np.savez_compressed(temporary, **arrays)
        # numpy appends .npz when the target does not already end with it.
        produced = Path(temporary if temporary.endswith(".npz") else f"{temporary}.npz")
        os.replace(produced, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


def read_npz(path: Path) -> dict[str, np.ndarray]:
    """Read an NPZ archive into a dictionary of arrays."""
    with np.load(Path(path)) as archive:
        return {key: archive[key] for key in archive.files}
