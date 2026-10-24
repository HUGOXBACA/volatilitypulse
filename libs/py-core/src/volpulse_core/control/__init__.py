# ─────────────────────────────────────────────────────────────────────────────
# gRPC control plane client and server for VolPulse ingestion engine.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

__all__ = [
    "IngestionControlClient",
    "IngestionControlServicer",
    "create_ingestion_control_server",
]