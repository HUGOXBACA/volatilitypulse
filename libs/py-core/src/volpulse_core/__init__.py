"""VolPulse shared Python library.

This package holds everything the analytics service needs that is *not* the
service itself:

* :mod:`volpulse.models`   – immutable domain types (slots, frozen).
* :mod:`volpulse.schemas`  – pandera schemas validating upstream payloads.
* :mod:`volpulse.clients`  – IVolatility REST/WebSocket clients.
* :mod:`volpulse.io`       – Parquet / NPZ artefact persistence.
* :mod:`volpulse.observability` – metrics and structured logging.

The service that consumes this library lives in ``services/analytics-py``.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
