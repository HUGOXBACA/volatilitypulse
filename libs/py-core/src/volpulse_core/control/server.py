# ─────────────────────────────────────────────────────────────────────────────
# gRPC server for the VolPulse ingestion control plane.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import grpc
from google.protobuf import timestamp_pb2

from volpulse.ingestion.v1 import control_pb2, control_pb2_grpc

logger = logging.getLogger(__name__)

__all__ = ["IngestionControlServicer", "create_ingestion_control_server"]


class IngestionControlServicer(control_pb2_grpc.IngestionControlServiceServicer):  # type: ignore[misc]
    """gRPC servicer for the ingestion control plane.

    This servicer handles:
    - Historical backfill requests
    - Ingestion engine health/status queries
    - Surface recomputation triggers
    """

    def __init__(self) -> None:
        self._active_symbols: set[str] = set()
        self._records_published: int = 0
        self._records_dropped: int = 0
        self._last_poll_time: float = time.time()
        self._pacing_delay_ms: int = 0
        self._checkpoint_position: str = "0"
        self._jobs: dict[str, dict[str, Any]] = {}

    async def FetchBackfill(
        self,
        request: control_pb2.FetchBackfillRequest,
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> control_pb2.FetchBackfillResponse:
        """Handle historical backfill request."""
        logger.info(
            "Backfill requested for %s from %s to %s (analytics=%s)",
            request.underlying_symbol,
            request.from_.ToDatetime() if request.from_ else "unknown",
            request.to.ToDatetime() if request.to else "unknown",
            request.run_analytics,
        )

        # Generate job ID
        job_id = f"backfill-{int(time.time() * 1000)}"

        # Store job info
        self._jobs[job_id] = {
            "type": "backfill",
            "underlying_symbol": request.underlying_symbol,
            "from": request.from_,
            "to": request.to,
            "run_analytics": request.run_analytics,
            "status": "accepted",
            "created_at": time.time(),
        }

        # Track active symbol
        self._active_symbols.add(request.underlying_symbol)

        response = control_pb2.FetchBackfillResponse(
            job_id=job_id,
            state="accepted",
            accepted_at=timestamp_pb2.Timestamp(seconds=int(time.time())),
        )
        return response

    async def GetIngestStatus(
        self,
        request: control_pb2.GetIngestStatusRequest,
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> control_pb2.GetIngestStatusResponse:
        """Return ingestion engine health and status."""
        return control_pb2.GetIngestStatusResponse(
            healthy=True,
            active_symbols=list(self._active_symbols),
            last_poll_age_ms=int((time.time() - self._last_poll_time) * 1000),
            records_published=self._records_published,
            records_dropped=self._records_dropped,
            current_pacing_delay_ms=self._pacing_delay_ms,
            checkpoint_position=self._checkpoint_position,
        )

    async def RecomputeSurface(
        self,
        request: control_pb2.RecomputeSurfaceRequest,
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> control_pb2.RecomputeSurfaceResponse:
        """Trigger surface recomputation."""
        logger.info("Surface recomputation requested for %s", request.underlying_symbol)

        job_id = f"recompute-{int(time.time() * 1000)}"

        as_of = request.as_of.ToDatetime() if request.as_of else datetime.now()

        self._jobs[job_id] = {
            "type": "recompute",
            "underlying_symbol": request.underlying_symbol,
            "as_of": as_of,
            "status": "accepted",
            "created_at": time.time(),
        }

        response = control_pb2.RecomputeSurfaceResponse(
            accepted=True,
            job_id=job_id,
        )
        return response

    # ── Internal methods for ingestion engine integration ────────────────────

    def record_published(self, count: int = 1) -> None:
        """Record published records."""
        self._records_published += count
        self._last_poll_time = time.time()

    def record_dropped(self, count: int = 1) -> None:
        """Record dropped records."""
        self._records_dropped += count

    def set_pacing_delay(self, delay_ms: int) -> None:
        """Set current pacing delay."""
        self._pacing_delay_ms = delay_ms

    def set_checkpoint(self, position: str) -> None:
        """Update checkpoint position."""
        self._checkpoint_position = position

    def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        """Get job status by ID."""
        return self._jobs.get(job_id)


async def create_ingestion_control_server(
    servicer: IngestionControlServicer | None = None,
    host: str = "[::]",
    port: int = 50051,
    max_workers: int = 10,
) -> grpc.aio.Server:
    """Create and start gRPC server for ingestion control.

    Args:
        servicer: Optional custom servicer; creates default if not provided.
        host: Host to bind to.
        port: Port to listen on.
        max_workers: Maximum number of worker threads.

    Returns:
        Started gRPC server.
    """
    if servicer is None:
        servicer = IngestionControlServicer()

    server = grpc.aio.server(ThreadPoolExecutor(max_workers=max_workers))
    control_pb2_grpc.add_IngestionControlServiceServicer_to_server(servicer, server)

    listen_addr = f"{host}:{port}"
    server.add_insecure_port(listen_addr)

    await server.start()
    logger.info("Ingestion control server started on %s", listen_addr)

    return server


async def run_control_server(
    host: str = "[::]",
    port: int = 50051,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Run the control server until shutdown.

    Args:
        host: Host to bind to.
        port: Port to listen on.
        shutdown_event: Optional external shutdown signal.
    """
    server = await create_ingestion_control_server(host=host, port=port)

    shutdown = shutdown_event or asyncio.Event()

    try:
        await shutdown.wait()
    finally:
        logger.info("Shutting down control server...")
        await server.stop(grace=5)
        logger.info("Control server stopped")