# ─────────────────────────────────────────────────────────────────────────────
# IVolatility API exceptions.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations


class IVolatilityError(Exception):
    """Base exception for all IVolatility client errors."""


class IVolatilityAuthError(IVolatilityError):
    """Authentication failed (bad credentials, expired token, 401/403)."""


class IVolatilityRateLimitError(IVolatilityError):
    """Upstream rate limit exceeded (429) or client pacing misconfigured."""


class IVolatilityAPIError(IVolatilityError):
    """The upstream returned a non-success status (400, 500, etc.)."""

    def __init__(self, status_code: int, message: str, url: str | None = None) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(f"IVolatility API error {status_code}: {message}")


class IVolatilityPendingError(IVolatilityError):
    """The upstream accepted the request but the result is not ready yet.

    The response carries a ``urlForDetails`` that must be polled until the
    ``urlForDownloads`` is published.
    """

    def __init__(self, details_url: str, message: str = "job pending") -> None:
        self.details_url = details_url
        super().__init__(message)
