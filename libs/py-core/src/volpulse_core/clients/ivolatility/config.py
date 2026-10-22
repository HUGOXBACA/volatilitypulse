# ─────────────────────────────────────────────────────────────────────────────
# IVolatility runtime configuration.
#
# Reads from environment variables (populated from ``.env``). All values are
# optional except credentials, which are required before any call that needs
# authentication.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from pydantic_settings import BaseSettings


class IVolatilitySettings(BaseSettings):
    """Runtime configuration for the IVolatility REST client."""

    model_config = {"env_prefix": "IVOL_", "env_file": ".env", "extra": "ignore"}

    # ── Base URL ──────────────────────────────────────────────────────────
    base_url: str = "https://restapi.ivolatility.com"

    # ── Credentials ───────────────────────────────────────────────────────
    # Three auth modes: API key (api_key), username+password, or bearer token.
    # At least one is required before any call that needs authentication.
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    token: str | None = None

    # ── Client behaviour ──────────────────────────────────────────────────
    timeout_seconds: float = 30.0
    rate_limit_rps: float = 1.0
    max_concurrency: int = 4
    max_retries: int = 3
    backoff_base_seconds: float = 1.0

    # ── Output ────────────────────────────────────────────────────────────
    default_output_dir: str = "var/artifacts/ivolatility"
    default_format: str = "parquet"  # parquet | json | csv
