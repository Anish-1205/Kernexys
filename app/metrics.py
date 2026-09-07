"""Prometheus metrics for Kernexys API."""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager


class MetricsCollector:
    """Collect and expose Prometheus metrics for Kernexys."""

    def __init__(self) -> None:
        """Initialize metrics collector."""
        self._request_count = {}
        self._request_latency = {}
        self._inference_latency = {}
        self._queue_depth = {}
        self._queue_errors = {}
        self._model_deployments_total = 0
        self._model_versions_total = 0
        self._kubernetes_syncs = {}
        self._kubernetes_sync_errors = {}

    @asynccontextmanager
    async def track_request(
        self,
        method: str,
        path: str,
    ) -> AsyncGenerator[None, None]:
        """Context manager to track HTTP request metrics."""
        start_time = time.monotonic()
        status_code = "unknown"
        try:
            yield
            status_code = "200"
        except Exception as exc:
            status_code = type(exc).__name__
            raise
        finally:
            duration = time.monotonic() - start_time
            key = (method, path, status_code)
            if key not in self._request_count:
                self._request_count[key] = 0
                self._request_latency[key] = []
            self._request_count[key] += 1
            self._request_latency[key].append(duration)

    @asynccontextmanager
    async def track_inference(
        self,
        namespace: str,
        deployment_name: str,
    ) -> AsyncGenerator[None, None]:
        """Context manager to track inference latency."""
        start_time = time.monotonic()
        try:
            yield
        finally:
            duration = time.monotonic() - start_time
            key = f"{namespace}/{deployment_name}"
            if key not in self._inference_latency:
                self._inference_latency[key] = []
            self._inference_latency[key].append(duration)

    def track_queue_depth(
        self,
        namespace: str,
        deployment_name: str,
        depth: int,
    ) -> None:
        """Track async queue depth."""
        key = f"{namespace}/{deployment_name}"
        self._queue_depth[key] = depth

    def track_queue_error(
        self,
        namespace: str,
        deployment_name: str,
        error_type: str,
    ) -> None:
        """Track async queue errors."""
        key = (f"{namespace}/{deployment_name}", error_type)
        if key not in self._queue_errors:
            self._queue_errors[key] = 0
        self._queue_errors[key] += 1

    def set_model_deployments_total(self, count: int) -> None:
        """Set total number of model deployments."""
        self._model_deployments_total = count

    def set_model_versions_total(self, count: int) -> None:
        """Set total number of model versions in registry."""
        self._model_versions_total = count

    def track_kubernetes_sync(
        self,
        deployment_name: str,
        duration: float,
        success: bool = True,
    ) -> None:
        """Track Kubernetes controller sync metrics."""
        key = deployment_name
        if key not in self._kubernetes_syncs:
            self._kubernetes_syncs[key] = []
        self._kubernetes_syncs[key].append({"duration": duration, "success": success})

        if not success:
            error_key = deployment_name
            if error_key not in self._kubernetes_sync_errors:
                self._kubernetes_sync_errors[error_key] = 0
            self._kubernetes_sync_errors[error_key] += 1

    def to_prometheus_format(self) -> str:
        """Export metrics in Prometheus exposition format."""
        lines = [
            "# HELP kernexys_http_requests_total Total HTTP requests processed",
            "# TYPE kernexys_http_requests_total counter",
        ]
        for (method, path, status), count in self._request_count.items():
            lines.append(
                f'kernexys_http_requests_total{{method="{method}",'
                f'path="{path}",status="{status}"}} {count}'
            )

        lines.extend(
            [
                "# HELP kernexys_http_request_duration_seconds HTTP request latency",
                "# TYPE kernexys_http_request_duration_seconds histogram",
            ]
        )
        for (method, path, status), durations in self._request_latency.items():
            if durations:
                p50 = sorted(durations)[len(durations) // 2]
                p95 = sorted(durations)[int(len(durations) * 0.95)]
                p99 = sorted(durations)[int(len(durations) * 0.99)]
                lines.append(
                    f'kernexys_http_request_duration_seconds_p50{{method="{method}",'
                    f'path="{path}",status="{status}"}} {p50}'
                )
                lines.append(
                    f'kernexys_http_request_duration_seconds_p95{{method="{method}",'
                    f'path="{path}",status="{status}"}} {p95}'
                )
                lines.append(
                    f'kernexys_http_request_duration_seconds_p99{{method="{method}",'
                    f'path="{path}",status="{status}"}} {p99}'
                )

        lines.extend(
            [
                "# HELP kernexys_inference_latency_seconds Inference request latency",
                "# TYPE kernexys_inference_latency_seconds histogram",
            ]
        )
        for deployment, durations in self._inference_latency.items():
            if durations:
                p50 = sorted(durations)[len(durations) // 2]
                p95 = sorted(durations)[int(len(durations) * 0.95)]
                p99 = sorted(durations)[int(len(durations) * 0.99)]
                lines.append(
                    f'kernexys_inference_latency_seconds_p50{{deployment="{deployment}"}} {p50}'
                )
                lines.append(
                    f'kernexys_inference_latency_seconds_p95{{deployment="{deployment}"}} {p95}'
                )
                lines.append(
                    f'kernexys_inference_latency_seconds_p99{{deployment="{deployment}"}} {p99}'
                )

        lines.extend(
            [
                "# HELP kernexys_async_queue_depth Number of pending inference jobs",
                "# TYPE kernexys_async_queue_depth gauge",
            ]
        )
        for deployment, depth in self._queue_depth.items():
            lines.append(f'kernexys_async_queue_depth{{deployment="{deployment}"}} {depth}')

        lines.extend(
            [
                "# HELP kernexys_async_queue_errors_total Async queue error count",
                "# TYPE kernexys_async_queue_errors_total counter",
            ]
        )
        for (deployment, error_type), count in self._queue_errors.items():
            lines.append(
                f'kernexys_async_queue_errors_total{{deployment="{deployment}",'
                f'type="{error_type}"}} {count}'
            )

        lines.extend(
            [
                "# HELP kernexys_model_deployments_total Total model deployments",
                "# TYPE kernexys_model_deployments_total gauge",
                f"kernexys_model_deployments_total {self._model_deployments_total}",
            ]
        )

        lines.extend(
            [
                "# HELP kernexys_model_versions_total Total model versions in registry",
                "# TYPE kernexys_model_versions_total gauge",
                f"kernexys_model_versions_total {self._model_versions_total}",
            ]
        )

        lines.extend(
            [
                "# HELP kernexys_kubernetes_sync_duration_seconds Controller sync latency",
                "# TYPE kernexys_kubernetes_sync_duration_seconds histogram",
            ]
        )
        for deployment, syncs in self._kubernetes_syncs.items():
            if syncs:
                successful = [s for s in syncs if s["success"]]
                if successful:
                    durations = [s["duration"] for s in successful]
                    p50 = sorted(durations)[len(durations) // 2]
                    p95 = sorted(durations)[int(len(durations) * 0.95)]
                    p99 = sorted(durations)[int(len(durations) * 0.99)]
                    lines.append(
                        "kernexys_kubernetes_sync_duration_seconds_p50"
                        f'{{deployment="{deployment}"}} {p50}'
                    )
                    lines.append(
                        "kernexys_kubernetes_sync_duration_seconds_p95"
                        f'{{deployment="{deployment}"}} {p95}'
                    )
                    lines.append(
                        "kernexys_kubernetes_sync_duration_seconds_p99"
                        f'{{deployment="{deployment}"}} {p99}'
                    )

        lines.extend(
            [
                "# HELP kernexys_kubernetes_sync_errors_total Controller sync error count",
                "# TYPE kernexys_kubernetes_sync_errors_total counter",
            ]
        )
        for deployment, count in self._kubernetes_sync_errors.items():
            lines.append(
                f'kernexys_kubernetes_sync_errors_total{{deployment="{deployment}"}} {count}'
            )

        return "\n".join(lines) + "\n"
