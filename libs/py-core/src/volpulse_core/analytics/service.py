# ─────────────────────────────────────────────────────────────────────────────
# VolPulse Analytics Service Implementation.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

import grpc
from google.protobuf import timestamp_pb2
from volpulse.analytics.models import CachedSurface, SurfaceCache, SurfaceCacheConfig
from volpulse.surface import SurfaceConfig, SurfaceFitResult, fit_surface

from volpulse.analytics.v1 import analytics_pb2, analytics_pb2_grpc
from volpulse_core.models.chain import OptionChainSnapshot

logger = logging.getLogger(__name__)

__all__ = [
    "AnalyticsServicer",
    "create_analytics_server",
]


class AnalyticsServicer(analytics_pb2_grpc.AnalyticsServiceServicer):  # type: ignore[misc]
    """gRPC servicer for the analytics service."""

    def __init__(
        self,
        cache: SurfaceCache | None = None,
        snapshot_writer: Any | None = None,
        snapshot_reader: Any | None = None,
    ) -> None:
        self._cache = cache or SurfaceCache(SurfaceCacheConfig())
        self._snapshot_writer = snapshot_writer
        self._snapshot_reader = snapshot_reader
        self._jobs: dict[str, dict[str, Any]] = {}

    # ── gRPC Methods ────────────────────────────────────────────────────────

    async def GetSurface(
        self,
        request: analytics_pb2.GetSurfaceRequest,
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> analytics_pb2.GetSurfaceResponse:
        """Get the current fitted volatility surface for an underlying."""
        logger.info("GetSurface requested for %s", request.underlying_symbol)

        # Check cache first
        cached = self._cache.get(request.underlying_symbol)
        if cached and not self._is_stale(cached, request):
            surface = cached.to_proto()
            return analytics_pb2.GetSurfaceResponse(
                surface=surface,
                retrieved_at=self._now_ts(),
                from_cache=True,
            )

        # Build surface from latest snapshots
        surface_result = await self._build_surface(request.underlying_symbol, request.as_of)

        if surface_result:
            # Cache the result
            self._cache.put(request.underlying_symbol, surface_result)
            surface = surface_result.to_proto()
            return analytics_pb2.GetSurfaceResponse(
                surface=surface,
                retrieved_at=self._now_ts(),
                from_cache=False,
            )

        # Return empty surface if no data
        return analytics_pb2.GetSurfaceResponse(
            surface=analytics_pb2.VolatilitySurface(
                underlying_symbol=request.underlying_symbol,
                as_of=self._now_ts(),
            ),
            retrieved_at=self._now_ts(),
            from_cache=False,
        )

    async def GetGreeks(
        self,
        request: analytics_pb2.GetGreeksRequest,
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> analytics_pb2.GetGreeksResponse:
        """Get Greeks for specific contracts or all contracts for an underlying."""
        logger.info("GetGreeks requested for %s", request.underlying_symbol)

        greeks_map: dict[str, analytics_pb2.Greeks] = {}

        # Get surface for the underlying
        surface_request = analytics_pb2.GetSurfaceRequest(
            underlying_symbol=request.underlying_symbol,
            as_of=request.as_of,
        )
        surface_response = await self.GetSurface(surface_request, context)

        if not surface_response.surface.points:
            return analytics_pb2.GetGreeksResponse(
                greeks={},
                retrieved_at=self._now_ts(),
                from_cache=True,
            )

        # For now, return placeholder Greeks. In production, compute from surface.
        # This would use the fitted surface to compute Greeks for each contract.

        return analytics_pb2.GetGreeksResponse(
            greeks=greeks_map,
            retrieved_at=self._now_ts(),
            from_cache=False,
        )

    async def RecomputeSurface(
        self,
        request: analytics_pb2.RecomputeSurfaceRequest,
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> analytics_pb2.RecomputeSurfaceResponse:
        """Trigger a surface recomputation."""
        logger.info("RecomputeSurface requested for %s", request.underlying_symbol)

        job_id = f"recompute-{uuid.uuid4().hex[:8]}"
        self._jobs[job_id] = {
            "type": "recompute",
            "underlying_symbol": request.underlying_symbol,
            "as_of": request.as_of,
            "force": request.force,
            "status": "accepted",
            "created_at": time.time(),
        }

        # Invalidate cache
        if request.force:
            self._cache.invalidate(request.underlying_symbol)

        # Kick off background recomputation
        asyncio.create_task(self._recompute_background(job_id, request))

        return analytics_pb2.RecomputeSurfaceResponse(
            job_id=job_id,
            state="accepted",
            accepted_at=self._now_ts(),
        )

    async def GetSurfaceHistory(
        self,
        request: analytics_pb2.GetSurfaceHistoryRequest,
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> analytics_pb2.GetSurfaceHistoryResponse:
        """Get historical surface snapshots for an underlying."""
        logger.info("GetSurfaceHistory requested for %s", request.underlying_symbol)

        # In production, this would query the snapshot store
        # For now, return empty
        return analytics_pb2.GetSurfaceHistoryResponse(surfaces=[])

    async def GetGreeksHistory(
        self,
        request: analytics_pb2.GetGreeksHistoryRequest,
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> analytics_pb2.GetGreeksHistoryResponse:
        """Get Greeks history for a specific contract."""
        logger.info("GetGreeksHistory requested for %s", request.contract_id)

        # In production, this would query the Greeks history store
        return analytics_pb2.GetGreeksHistoryResponse(
            greeks={},
            retrieved_at=self._now_ts(),
        )

    async def WatchSurface(
        self,
        request: analytics_pb2.GetSurfaceRequest,
        context: grpc.aio.ServicerContext[Any, Any],
    ) -> analytics_pb2.GetSurfaceResponse:
        """Server-side streaming for real-time surface updates."""
        logger.info("WatchSurface requested for %s", request.underlying_symbol)

        # Send initial surface
        surface_response = await self.GetSurface(request, context)
        yield surface_response

        # Then stream updates (simplified - in production would use pub/sub)
        while True:
            if hasattr(context, 'is_active') and not context.is_active():
                break
            await asyncio.sleep(5.0)
            surface_response = await self.GetSurface(request, context)
            yield surface_response

    # ── Internal Methods ──────────────────────────────────────────────────

    def _is_stale(self, cached: CachedSurface, request: analytics_pb2.GetSurfaceRequest) -> bool:
        """Check if cached surface is stale."""
        if request.as_of:
            return False  # If specific timestamp requested, use cache
        # Otherwise, consider stale after 30 seconds
        age = time.time() - cached.timestamp
        return bool(age > 30)

    def _now_ts(self) -> timestamp_pb2.Timestamp:
        """Get current time as protobuf Timestamp."""
        ts = timestamp_pb2.Timestamp()
        ts.GetCurrentTime()
        return ts

    async def _build_surface(
        self,
        underlying_symbol: str,
        as_of: timestamp_pb2.Timestamp | None = None,
    ) -> SurfaceFitResult | None:
        """Build surface from latest snapshots."""
        if not self._snapshot_reader:
            return None

        # Read recent snapshots
        snapshots = await self._read_recent_snapshots(underlying_symbol, as_of)

        if not snapshots:
            return None

        # Fit surface
        config = SurfaceConfig(method="SVI", check_arbitrage=True)
        result = fit_surface(snapshots, config=config)
        return result

    async def _read_recent_snapshots(
        self,
        underlying_symbol: str,
        as_of: timestamp_pb2.Timestamp | None = None,
    ) -> list[OptionChainSnapshot]:
        """Read recent snapshots for an underlying."""
        if not self._snapshot_reader:
            return []

        # In production, this would query the snapshot store
        # For now, return empty
        return []

    async def _recompute_background(
        self,
        job_id: str,
        request: analytics_pb2.RecomputeSurfaceRequest,
    ) -> None:
        """Background task to recompute surface."""
        self._jobs[job_id]["status"] = "running"

        try:
            # Build new surface
            result = await self._build_surface(request.underlying_symbol, request.as_of)

            if result:
                self._cache.put(request.underlying_symbol, result)
                self._jobs[job_id]["status"] = "completed"
            else:
                self._jobs[job_id]["status"] = "failed"
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Background recompute failed for %s: %s", job_id, e)
            self._jobs[job_id]["status"] = "failed"

    def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        """Get job status by ID."""
        return self._jobs.get(job_id)


# ── Server Factory ──────────────────────────────────────────────────────────


async def create_analytics_server(
    host: str = "[::]",
    port: int = 50052,
    max_workers: int = 10,
    cache: Any | None = None,
    snapshot_writer: Any | None = None,
    snapshot_reader: Any | None = None,
) -> grpc.aio.Server:
    """Create and start gRPC server for analytics service."""
    servicer = AnalyticsServicer(
        cache=cache,
        snapshot_writer=snapshot_writer,
        snapshot_reader=snapshot_reader,
    )

    server = grpc.aio.server()
    analytics_pb2_grpc.add_AnalyticsServiceServicer_to_server(servicer, server)

    listen_addr = f"{host}:{port}"
    server.add_insecure_port(listen_addr)

    await server.start()
    logger.info("Analytics server started on %s", listen_addr)

    return server


async def run_analytics_server(
    host: str = "[::]",
    port: int = 50052,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Run the analytics server until shutdown."""
    server = await create_analytics_server(host=host, port=port)

    shutdown = shutdown_event or asyncio.Event()

    try:
        await shutdown.wait()
    finally:
        logger.info("Shutting down analytics server...")
        await server.stop(grace=5)
        logger.info("Analytics server stopped")