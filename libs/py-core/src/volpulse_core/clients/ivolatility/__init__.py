"""IVolatility API client: pacing, pagination and payload validation.

The upstream quota is metered, so every call goes through
:class:`~volpulse.clients.ivolatility.rate_limit.RateLimiter`, and every wide
query goes through
:func:`~volpulse.clients.ivolatility.pagination.poll_for_download`.
"""

from __future__ import annotations

from volpulse_core.clients.ivolatility.pagination import Page, iter_pages, poll_for_download
from volpulse_core.clients.ivolatility.rate_limit import RateLimiter

__all__ = ["Page", "RateLimiter", "iter_pages", "poll_for_download"]
