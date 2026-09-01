"""Prometheus metrics owned by one runtime application instance."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class RuntimeMetrics:
    def __init__(self, model: str, version: str) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.requests = Counter(
            "kernexys_inference_requests_total",
            "Inference requests completed by outcome.",
            ("model", "version", "outcome"),
            registry=self.registry,
        )
        self.duration = Histogram(
            "kernexys_inference_duration_seconds",
            "End-to-end inference HTTP request duration.",
            ("model", "version"),
            buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
            registry=self.registry,
        )
        self.info = Gauge(
            "kernexys_runtime_info",
            "Identity of the running model artifact.",
            ("model", "version"),
            registry=self.registry,
        )
        self.info.labels(model=model, version=version).set(1)
        self.model = model
        self.version = version

    def observe_inference(self, outcome: str, duration_seconds: float) -> None:
        labels = {"model": self.model, "version": self.version}
        self.requests.labels(**labels, outcome=outcome).inc()
        self.duration.labels(**labels).observe(duration_seconds)
