# ─────────────────────────────────────────────────────────────────────────────
# Health checks for VolPulse services.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "HealthCheck",
    "HealthCheckRegistry",
    "HealthStatus",
    "get_health_registry",
]


class HealthStatus(str, Enum):
    """Health check status levels."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    """Result of a single health check."""

    name: str
    status: HealthStatus
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
        }


class HealthCheck(ABC):
    """Abstract base class for health checks."""

    def __init__(self, name: str, critical: bool = True, timeout_seconds: float = 5.0) -> None:
        self.name = name
        self.critical = critical
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    async def check(self) -> HealthCheckResult:
        """Execute the health check and return result."""
        ...

    async def run(self) -> HealthCheckResult:
        """Run the health check with timeout."""
        start_time = time.perf_counter()
        try:
            result = await asyncio.wait_for(self.check(), timeout=self.timeout_seconds)
        except TimeoutError:
            duration = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Health check timed out after {self.timeout_seconds}s",
                duration_ms=duration,
            )
        except (OSError, ValueError, RuntimeError) as e:
            duration = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {e}",
                duration_ms=duration,
            )
        else:
            result.duration_ms = (time.perf_counter() - start_time) * 1000
            return result


class HealthCheckRegistry:
    """Registry for managing multiple health checks."""

    def __init__(self) -> None:
        self._checks: dict[str, HealthCheck] = {}
        self._lock = threading.Lock()

    def register(self, check: HealthCheck) -> None:
        """Register a health check."""
        with self._lock:
            if check.name in self._checks:
                logger.warning("Health check %s already registered, replacing", check.name)
            self._checks[check.name] = check

    def unregister(self, name: str) -> bool:
        """Unregister a health check."""
        with self._lock:
            if name in self._checks:
                del self._checks[name]
                return True
            return False

    def get_check(self, name: str) -> HealthCheck | None:
        """Get a health check by name."""
        with self._lock:
            return self._checks.get(name)

    def list_checks(self) -> list[str]:
        """List all registered check names."""
        with self._lock:
            return list(self._checks.keys())

    async def run_all(self) -> dict[str, HealthCheckResult]:
        """Run all registered health checks."""
        with self._lock:
            checks = list(self._checks.values())

        results = await asyncio.gather(
            *[check.run() for check in checks],
            return_exceptions=True,
        )

        results_dict = {}
        for check, result in zip(self._checks.keys(), results):
            if isinstance(result, Exception):
                logger.error("Health check %s raised exception: %s", check.name, result)
                result = HealthCheckResult(
                    name=check.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check raised exception: {result}",
                )
            results_dict[check.name] = result

        return results_dict

    async def get_overall_status(self) -> HealthStatus:
        """Get overall system health status."""
        await self.run_all()

        if not self._checks:
            return HealthStatus.UNKNOWN

        has_unhealthy = any(r.status == HealthStatus.UNHEALTHY for r in self._checks.values())
        has_degraded = any(r.status == HealthStatus.DEGRADED for r in self._checks.values())

        if has_unhealthy:
            return HealthStatus.UNHEALTHY
        elif has_degraded:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY

    async def get_detailed_report(self) -> dict[str, Any]:
        """Get detailed health report."""
        results = await self.run_all()
        overall = await self.get_overall_status()

        return {
            "status": overall.value,
            "timestamp": datetime.now(UTC).isoformat(),
            "checks": {name: result.to_dict() for name, result in results.items()},
        }


# Global registry instance
_health_registry: HealthCheckRegistry | None = None
_registry_lock = threading.Lock()


def get_health_registry() -> HealthCheckRegistry:
    """Get the global health check registry (singleton)."""
    global _health_registry
    if _health_registry is None:
        with _registry_lock:
            if _health_registry is None:
                _health_registry = HealthCheckRegistry()
    return _health_registry


# ─── Common Health Checks ────────────────────────────────────────────────────


class HTTPHealthCheck(HealthCheck):
    """Health check for HTTP endpoints."""

    def __init__(
        self,
        name: str,
        url: str,
        expected_status: int = 200,
        timeout_seconds: float = 5.0,
        critical: bool = True,
    ) -> None:
        super().__init__(name, critical, timeout_seconds)
        self.url = url
        self.expected_status = expected_status

    async def check(self) -> HealthCheckResult:
        import httpx

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(self.url)
                duration_ms = (time.perf_counter() - start) * 1000

                if response.status_code == self.expected_status:
                    return HealthCheckResult(
                        name=self.name,
                        status=HealthStatus.HEALTHY,
                        message=f"HTTP {response.status_code}",
                        duration_ms=duration_ms,
                    )
                else:
                    return HealthCheckResult(
                        name=self.name,
                        status=HealthStatus.UNHEALTHY,
                        message=f"Unexpected status: {response.status_code}",
                        details={"expected": self.expected_status, "actual": response.status_code},
                        duration_ms=duration_ms,
                    )
        except (OSError, ValueError, RuntimeError) as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Request failed: {e}",
                duration_ms=duration_ms,
            )


class DatabaseHealthCheck(HealthCheck):
    """Health check for database connections."""

    def __init__(
        self,
        name: str,
        connection_string: str,
        query: str = "SELECT 1",
        timeout_seconds: float = 5.0,
        critical: bool = True,
    ) -> None:
        super().__init__(name, critical, timeout_seconds)
        self.connection_string = connection_string
        self.query = query

    async def check(self) -> HealthCheckResult:
        import asyncpg

        start = time.perf_counter()
        try:
            conn = await asyncio.wait_for(
                asyncpg.connect(self.connection_string, timeout=self.timeout_seconds),
                timeout=self.timeout_seconds,
            )
            await conn.execute(self.query)
            await conn.close()
            duration_ms = (time.perf_counter() - start) * 1000

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message="Database connection successful",
                duration_ms=duration_ms,
            )
        except (OSError, ValueError, RuntimeError) as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Database check failed: {e}",
                duration_ms=duration_ms,
            )


class KafkaHealthCheck(HealthCheck):
    """Health check for Kafka connectivity."""

    def __init__(
        self,
        name: str,
        bootstrap_servers: str,
        timeout_seconds: float = 5.0,
        critical: bool = True,
    ) -> None:
        super().__init__(name, critical, timeout_seconds)
        self.bootstrap_servers = bootstrap_servers

    async def check(self) -> HealthCheckResult:
        from confluent_kafka import Producer

        start = time.perf_counter()
        try:
            producer = Producer({"bootstrap.servers": self.bootstrap_servers})
            # Test connection by getting metadata
            metadata = producer.list_topics(timeout=self.timeout_seconds)
            duration_ms = (time.perf_counter() - start) * 1000

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message=f"Kafka cluster reachable ({len(metadata.topics)} topics)",
                duration_ms=duration_ms,
            )
        except (OSError, ValueError, RuntimeError) as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Kafka check failed: {e}",
                duration_ms=duration_ms,
            )


class RedisHealthCheck(HealthCheck):
    """Health check for Redis connectivity."""

    def __init__(
        self,
        name: str,
        url: str,
        timeout_seconds: float = 5.0,
        critical: bool = True,
    ) -> None:
        super().__init__(name, critical, timeout_seconds)
        self.url = url

    async def check(self) -> HealthCheckResult:
        import redis.asyncio as redis

        start = time.perf_counter()
        try:
            client = redis.from_url(self.url, socket_timeout=self.timeout_seconds)
            await client.ping()
            await client.close()
            duration_ms = (time.perf_counter() - start) * 1000

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message="Redis ping successful",
                duration_ms=duration_ms,
            )
        except (OSError, ValueError, RuntimeError) as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Redis check failed: {e}",
                duration_ms=duration_ms,
            )


class DiskSpaceHealthCheck(HealthCheck):
    """Health check for disk space."""

    def __init__(
        self,
        name: str,
        path: str = "/",
        warning_threshold: float = 0.8,
        critical_threshold: float = 0.95,
        timeout_seconds: float = 5.0,
        critical: bool = True,
    ) -> None:
        super().__init__(name, critical, timeout_seconds)
        self.path = path
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold

    async def check(self) -> HealthCheckResult:
        import shutil

        start = time.perf_counter()
        try:
            total, used, free = shutil.disk_usage(self.path)
            used_ratio = used / total
            duration_ms = (time.perf_counter() - start) * 1000

            if used_ratio >= self.critical_threshold:
                status = HealthStatus.UNHEALTHY
                message = f"Disk usage critical: {used_ratio:.1%}"
            elif used_ratio >= self.warning_threshold:
                status = HealthStatus.DEGRADED
                message = f"Disk usage warning: {used_ratio:.1%}"
            else:
                status = HealthStatus.HEALTHY
                message = f"Disk usage OK: {used_ratio:.1%}"

            return HealthCheckResult(
                name=self.name,
                status=status,
                message=message,
                details={
                    "total_gb": total / (1024**3),
                    "used_gb": used / (1024**3),
                    "free_gb": free / (1024**3),
                    "used_ratio": used_ratio,
                },
                duration_ms=duration_ms,
            )
        except (OSError, ValueError, RuntimeError) as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Disk check failed: {e}",
                duration_ms=duration_ms,
            )


class MemoryHealthCheck(HealthCheck):
    """Health check for memory usage."""

    def __init__(
        self,
        name: str,
        warning_threshold: float = 0.8,
        critical_threshold: float = 0.95,
        timeout_seconds: float = 1.0,
        critical: bool = True,
    ) -> None:
        super().__init__(name, critical, timeout_seconds)
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold

    async def check(self) -> HealthCheckResult:
        import psutil

        start = time.perf_counter()
        try:
            mem = psutil.virtual_memory()
            used_ratio = mem.percent / 100.0
            duration_ms = (time.perf_counter() - start) * 1000

            if used_ratio >= self.critical_threshold:
                status = HealthStatus.UNHEALTHY
                message = f"Memory usage critical: {used_ratio:.1%}"
            elif used_ratio >= self.warning_threshold:
                status = HealthStatus.DEGRADED
                message = f"Memory usage warning: {used_ratio:.1%}"
            else:
                status = HealthStatus.HEALTHY
                message = f"Memory usage OK: {used_ratio:.1%}"

            return HealthCheckResult(
                name=self.name,
                status=status,
                message=message,
                details={
                    "total_gb": mem.total / (1024**3),
                    "available_gb": mem.available / (1024**3),
                    "used_ratio": used_ratio,
                },
                duration_ms=duration_ms,
            )
        except (OSError, ValueError, RuntimeError) as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Memory check failed: {e}",
                duration_ms=duration_ms,
            )


class CustomHealthCheck(HealthCheck):
    """Generic health check with custom callable."""

    def __init__(
        self,
        name: str,
        check_fn: callable,
        critical: bool = True,
        timeout_seconds: float = 5.0,
    ) -> None:
        super().__init__(name, critical, timeout_seconds)
        self._check_fn = check_fn

    async def check(self) -> HealthCheckResult:
        start = time.perf_counter()
        try:
            if asyncio.iscoroutinefunction(self._check_fn):
                result = await self._check_fn()
            else:
                result = self._check_fn()

            duration_ms = (time.perf_counter() - start) * 1000

            if isinstance(result, HealthCheckResult):
                result.duration_ms = duration_ms
                return result
            elif isinstance(result, bool):
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY,
                    duration_ms=duration_ms,
                )
            elif isinstance(result, dict):
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus(result.get("status", "healthy")),
                    message=result.get("message", ""),
                    details=result.get("details", {}),
                    duration_ms=duration_ms,
                )
            else:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Invalid check result type: {type(result)}",
                    duration_ms=duration_ms,
                )
        except (OSError, ValueError, RuntimeError) as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Check failed: {e}",
                duration_ms=duration_ms,
            )