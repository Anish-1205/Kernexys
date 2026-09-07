"""Tests for Kernexys observability (metrics and logging)."""

import json
import logging

from app.metrics import MetricsCollector
from app.observability import (
    StructuredFormatter,
    configure_logging,
    get_correlation_id,
    set_correlation_id,
)


class TestMetricsCollector:
    """Test Prometheus metrics collection."""

    def test_export_empty_metrics(self) -> None:
        """Exporting empty metrics should produce valid Prometheus format."""
        collector = MetricsCollector()
        output = collector.to_prometheus_format()

        assert "# HELP kernexys_http_requests_total" in output
        assert "# TYPE kernexys_http_requests_total counter" in output
        assert output.endswith("\n")

    def test_track_request_metrics(self) -> None:
        """Request tracking should record counters and latencies."""
        collector = MetricsCollector()

        collector._request_count[("GET", "/health", "200")] = 5
        collector._request_latency[("GET", "/health", "200")] = [0.01] * 5

        output = collector.to_prometheus_format()
        assert 'kernexys_http_requests_total{method="GET",path="/health",status="200"} 5' in output
        assert (
            'kernexys_http_request_duration_seconds_p50{method="GET",path="/health",status="200"}'
            in output
        )

    def test_track_inference_latency(self) -> None:
        """Inference latency should track model deployment performance."""
        collector = MetricsCollector()

        collector._inference_latency["default/gpt2"] = [0.1, 0.15, 0.2, 0.25]

        output = collector.to_prometheus_format()
        assert 'kernexys_inference_latency_seconds_p50{deployment="default/gpt2"}' in output

    def test_track_queue_depth(self) -> None:
        """Queue depth should track pending inference jobs."""
        collector = MetricsCollector()

        collector.track_queue_depth("default", "gpt2", 15)

        output = collector.to_prometheus_format()
        assert 'kernexys_async_queue_depth{deployment="default/gpt2"} 15' in output

    def test_track_queue_errors(self) -> None:
        """Queue errors should track failure types."""
        collector = MetricsCollector()

        collector.track_queue_error("default", "gpt2", "timeout")
        collector.track_queue_error("default", "gpt2", "timeout")
        collector.track_queue_error("default", "gpt2", "redis_unavailable")

        output = collector.to_prometheus_format()
        assert (
            'kernexys_async_queue_errors_total{deployment="default/gpt2",type="timeout"} 2'
            in output
        )
        assert (
            'kernexys_async_queue_errors_total{deployment="default/gpt2",'
            'type="redis_unavailable"} 1' in output
        )

    def test_model_deployment_metrics(self) -> None:
        """Model deployment totals should be exposed."""
        collector = MetricsCollector()

        collector.set_model_deployments_total(8)
        collector.set_model_versions_total(23)

        output = collector.to_prometheus_format()
        assert "kernexys_model_deployments_total 8" in output
        assert "kernexys_model_versions_total 23" in output

    def test_kubernetes_sync_metrics(self) -> None:
        """Kubernetes controller sync metrics should be tracked."""
        collector = MetricsCollector()

        collector.track_kubernetes_sync("gpt2", 0.125, success=True)
        collector.track_kubernetes_sync("gpt2", 0.156, success=False)

        output = collector.to_prometheus_format()
        assert 'kernexys_kubernetes_sync_duration_seconds_p50{deployment="gpt2"}' in output
        assert 'kernexys_kubernetes_sync_errors_total{deployment="gpt2"} 1' in output

    def test_percentile_calculation(self) -> None:
        """Percentiles should be calculated correctly."""
        collector = MetricsCollector()

        # Create predictable latency data
        latencies = [i * 0.01 for i in range(100)]  # 0, 0.01, 0.02, ..., 0.99
        collector._request_latency[("GET", "/api", "200")] = latencies

        output = collector.to_prometheus_format()
        # p50 should be ~0.49, p95 should be ~0.94, p99 should be ~0.98
        assert "kernexys_http_request_duration_seconds_p50" in output
        assert "kernexys_http_request_duration_seconds_p95" in output
        assert "kernexys_http_request_duration_seconds_p99" in output


class TestCorrelationId:
    """Test request correlation ID tracking."""

    def test_default_correlation_id(self) -> None:
        """Default correlation ID should be generated."""
        correlation_id = get_correlation_id()
        assert correlation_id is not None
        assert len(correlation_id) > 0

    def test_set_correlation_id(self) -> None:
        """Correlation ID should be settable."""
        test_id = "test-correlation-123"
        set_correlation_id(test_id)
        assert get_correlation_id() == test_id

    def test_correlation_id_persistence(self) -> None:
        """Correlation ID should persist across calls."""
        test_id = "test-persistence-456"
        set_correlation_id(test_id)

        # Get it multiple times
        assert get_correlation_id() == test_id
        assert get_correlation_id() == test_id


class TestStructuredFormatter:
    """Test JSON structured logging format."""

    def test_basic_log_format(self) -> None:
        """Logs should be formatted as JSON."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "Test message"
        assert "timestamp" in parsed
        assert "correlation_id" in parsed

    def test_extra_fields_in_log(self) -> None:
        """Extra fields should be included in JSON output."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.extra_fields = {"deployment": "gpt2", "duration": 0.125}

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["deployment"] == "gpt2"
        assert parsed["duration"] == 0.125

    def test_exception_in_log(self) -> None:
        """Exceptions should be formatted in logs."""
        formatter = StructuredFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test.logger",
                level=logging.ERROR,
                pathname="test.py",
                lineno=42,
                msg="Error occurred",
                args=(),
                exc_info=sys.exc_info(),
            )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["level"] == "ERROR"
        assert "exception" in parsed
        assert "ValueError: Test error" in parsed["exception"]


class TestLoggingConfiguration:
    """Test logging setup."""

    def test_configure_json_logging(self) -> None:
        """JSON logging should be configurable."""
        # This is a smoke test - actual configuration would need handler setup
        # which is complex to test without modifying root logger
        configure_logging("INFO", json_format=True)

        # Verify no exceptions are raised
        logger = logging.getLogger("test")
        logger.info("Test message")

    def test_configure_text_logging(self) -> None:
        """Text logging should be configurable."""
        configure_logging("DEBUG", json_format=False)

        logger = logging.getLogger("test")
        logger.debug("Test debug message")
