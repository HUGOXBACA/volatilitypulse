# ─────────────────────────────────────────────────────────────────────────────
# Shared request/response models for the IVolatility REST API.
#
# Most endpoints return a common JSON envelope:
#
#   {
#     "status": { "executionTime", "recordsFound", "code", "urlForDetails", ... },
#     "query":  { ...echo of request... },
#     "data":   [ {...}, ... ]   # or a raw CSV string for some endpoints
#   }
#
# Wide historical queries return ``code: "PENDING"`` with a ``urlForDetails``;
# the client polls that URL until ``urlForDownloads`` is published, then
# fetches the actual payload.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Status(BaseModel):
    executionTime: int | None = None
    recordsFound: int | None = None
    code: str | None = None
    urlForDetails: str | None = None
    urlForDownloads: str | None = None
    queriesLeftEOD: int | None = None
    queriesLeftIntraday: int | None = None


class Query(BaseModel):
    requestUUID: str | None = None
    # Everything else is endpoint-specific; kept as arbitrary types.
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class APIResponse(BaseModel):
    status: Status
    query: Query | None = None
    data: list[dict[str, Any]] | str | None = None

    model_config = {"extra": "allow"}

    @property
    def is_pending(self) -> bool:
        return (self.status.code or "").upper() == "PENDING"

    @property
    def details_url(self) -> str | None:
        return self.status.urlForDetails

    @property
    def download_url(self) -> str | None:
        return self.status.urlForDownloads
