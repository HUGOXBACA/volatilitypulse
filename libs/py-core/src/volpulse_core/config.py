"""Runtime configuration.

Configuration is read from the environment (populated from ``.env``) exactly
once, at process start, and then passed down explicitly. No module reads
``os.environ`` at import time and no secret is ever logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

__all__ = ["Settings", "load_settings"]


def _require(name: str) -> str:
    """Read a mandatory environment variable.

    Raises:
        RuntimeError: The variable is missing or empty.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"required environment variable {name!r} is not set. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def _optional(name: str, default: str) -> str:
    """Read an optional environment variable, falling back to ``default``."""
    value = os.environ.get(name, "").strip()
    return value if value else default


def _float(name: str, default: float) -> float:
    """Read a float environment variable."""
    raw = _optional(name, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise RuntimeError(f"environment variable {name!r} is not a number: {raw!r}") from error


def _int(name: str, default: int) -> int:
    """Read an integer environment variable."""
    raw = _optional(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise RuntimeError(f"environment variable {name!r} is not an integer: {raw!r}") from error


@dataclass(frozen=True, slots=True)
class Settings:
    """The complete runtime configuration of a VolPulse service."""

    # ── Upstream provider ────────────────────────────────────────────────
    ivol_api_key: str
    ivol_base_url: str
    ivol_timeout_seconds: float
    ivol_rate_limit_rps: float
    ivol_max_concurrency: int

    # ── Broker ───────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str
    kafka_topic_options: str
    kafka_topic_quotes: str
    kafka_consumer_group: str

    # ── Storage ──────────────────────────────────────────────────────────
    timescale_host: str
    timescale_port: int
    timescale_db: str
    timescale_user: str
    timescale_password: str
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str

    # ── Observability ────────────────────────────────────────────────────
    prometheus_url: str
    influxdb_url: str
    sensu_url: str
    log_level: str
    log_format: str

    # ── Runtime paths ────────────────────────────────────────────────────
    binary_log_dir: Path
    checkpoint_dir: Path
    artifact_dir: Path

    @classmethod
    def from_env(cls) -> Settings:
        """Build the settings from the process environment.

        Raises:
            RuntimeError: A mandatory variable is missing or malformed.
        """
        return cls(
            ivol_api_key=_require("IVOL_API_KEY"),
            ivol_base_url=_optional("IVOL_BASE_URL", "https://api.ivolatility.com"),
            ivol_timeout_seconds=_float("IVOL_TIMEOUT_SECONDS", 30.0),
            ivol_rate_limit_rps=_float("IVOL_RATE_LIMIT_RPS", 1.0),
            ivol_max_concurrency=_int("IVOL_MAX_CONCURRENCY", 4),
            kafka_bootstrap_servers=_optional("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            kafka_topic_options=_optional("KAFKA_TOPIC_OPTIONS", "options.chain.streaming"),
            kafka_topic_quotes=_optional("KAFKA_TOPIC_QUOTES", "options.quotes.realtime"),
            kafka_consumer_group=_optional("KAFKA_CONSUMER_GROUP", "volpulse-analytics"),
            timescale_host=_optional("TIMESCALE_HOST", "localhost"),
            timescale_port=_int("TIMESCALE_PORT", 5432),
            timescale_db=_optional("TIMESCALE_DB", "volpulse"),
            timescale_user=_optional("TIMESCALE_USER", "volpulse"),
            timescale_password=_optional("TIMESCALE_PASSWORD", ""),
            postgres_host=_optional("POSTGRES_HOST", "localhost"),
            postgres_port=_int("POSTGRES_PORT", 5432),
            postgres_db=_optional("POSTGRES_DB", "volpulse_state"),
            postgres_user=_optional("POSTGRES_USER", "volpulse"),
            postgres_password=_optional("POSTGRES_PASSWORD", ""),
            prometheus_url=_optional("PROMETHEUS_URL", "http://localhost:9090"),
            influxdb_url=_optional("INFLUXDB_URL", "http://localhost:8086"),
            sensu_url=_optional("SENSU_URL", "http://localhost:8080"),
            log_level=_optional("LOG_LEVEL", "INFO"),
            log_format=_optional("LOG_FORMAT", "json"),
            binary_log_dir=Path(_optional("BINARY_LOG_DIR", "var/binary-logs")),
            checkpoint_dir=Path(_optional("CHECKPOINT_DIR", "var/checkpoints")),
            artifact_dir=Path(_optional("ARTIFACT_DIR", "var/artifacts")),
        )


def load_settings(dotenv_path: Path | None = None) -> Settings:
    """Load ``.env`` and build the settings.

    Args:
        dotenv_path: Explicit path to the environment file. Defaults to
            ``.env`` in the current working directory.

    Returns:
        The effective settings.
    """
    load_dotenv(dotenv_path if dotenv_path is not None else Path(".env"), override=False)
    return Settings.from_env()
