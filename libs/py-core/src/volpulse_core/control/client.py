# ─────────────────────────────────────────────────────────────────────────────
# gRPC client for the VolPulse ingestion control plane.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import types
from datetime import datetime
from typing import Any, Self

import grpc
from google.protobuf import timestamp_pb2

from volpulse.ingestion.v1 import control_pb2, control_pb2_grpc

logger = logging.getLogger(__name__)

__all__ = ["IngestionControlClient"]


class IngestionControlClient:
    """Async gRPC client for the ingestion control plane."""

    def __init__(
        self,
        target: str = "localhost:50051",
        credentials: grpc.ChannelCredentials | None = None,
    ) -> None:
        self._target = target
        self._credentials = credentials
        self._channel: grpc.aio.Channel | None = None
        self._stub: control_pb2_grpc.IngestionControlServiceStub | None = None

    async def connect(self) -> None:
        """Establish gRPC channel and create stub."""
        if self._channel is not None:
            return

        if self._credentials:
            self._channel = grpc.aio.secure_channel(self._target, self._credentials)
        else:
            self._channel = grpc.aio.insecure_channel(self._target)

        self._stub = control_pb2_grpc.IngestionControlServiceStub(self._channel)
        logger.info("Connected to ingestion control service at %s", self._target)

    async def close(self) -> None:
        """Close the gRPC channel."""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
            self._stub = None
            logger.info("Closed connection to ingestion control service")

    async def fetch_backfill(
        self,
        underlying_symbol: str,
        from_dt: datetime,
        to_dt: datetime,
        run_analytics: bool = False,
    ) -> str:
        """Request a historical backfill.

        Args:
            underlying_symbol: The underlying symbol to backfill.
            from_dt: Start of the historical window (inclusive).
            to_dt: End of the historical window (exclusive).
            run_analytics: Whether to replay through analytics engine.

        Returns:
            Job ID for tracking the backfill operation.
        """
        if self._stub is None:
            await self.connect()

        assert self._stub is not None

        from_ts = timestamp_pb2.Timestamp()
        from_ts.FromDatetime(from_dt)
        to_ts = timestamp_pb2.Timestamp()
        to_ts.FromDatetime(to_dt)

        request = control_pb2.FetchBackfillRequest(
            underlying_symbol=underlying_symbol,
            from_=from_ts,
            to=to_ts,
            run_analytics=run_analytics,
        )

        response = await self._stub.FetchBackfill(request)
        logger.info("Backfill request accepted: job_id=%s", response.job_id)
        return response.job_id  # type: ignore[no-any-return]

    async def get_ingest_status(self) -> dict[str, Any]:
        """Get ingestion engine health and status.

        Returns:
            Dictionary with status information.
        """
        if self._stub is None:
            await self.connect()

        assert self._stub is not None

        request = control_pb2.GetIngestStatusRequest()
        response = await self._stub.GetIngestStatus(request)

        return {
            "healthy": response.healthy,
            "active_symbols": list(response.active_symbols),
            "last_poll_age_ms": response.last_poll_age_ms,
            "records_published": response.records_published,
            "records_dropped": response.records_dropped,
            "current_pacing_delay_ms": response.current_pacing_delay_ms,
            "checkpoint_position": response.checkpoint_position,
        }

    async def recompute_surface(
        self,
        underlying_symbol: str,
        as_of: datetime | None = None,
    ) -> str:
        """Trigger a surface recomputation.

        Args:
            underlying_symbol: The underlying symbol to recompute.
            as_of: Optional timestamp for the surface; defaults to now.

        Returns:
            Job ID for tracking the recomputation.
        """
        if self._stub is None:
            await self.connect()

        assert self._stub is not None

        as_of_ts = None
        if as_of is not None:
            as_of_ts = timestamp_pb2.Timestamp()
            as_of_ts.FromDatetime(as_of)

        request = control_pb2.RecomputeSurfaceRequest(
            underlying_symbol=underlying_symbol,
            as_of=as_of_ts,
        )

        response = await self._stub.RecomputeSurface(request)
        logger.info("Surface recomputation accepted: job_id=%s", response.job_id)
        return response.job_id  # type: ignore[no-any-return]

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        await self.close()