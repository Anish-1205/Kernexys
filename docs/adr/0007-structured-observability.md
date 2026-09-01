# ADR 0007: Structured Observability Architecture

**Status**: Accepted

**Date**: 2025-01-XX

**Context**

Kernexys runs in production environments where debugging issues requires
understanding system behavior across API, workers, database, and Kubernetes.
Traditional logging (unstructured text) and simple counters are insufficient:

- Text logs cannot be easily aggregated or searched
- Metrics without context cannot diagnose specific failures
- Request tracing across async boundary is difficult
- Performance issues cannot be correlated with system state

Without observability, debugging production issues requires manual log
inspection, making MTTR (mean time to recovery) unacceptably high.

**Decision**

Implement structured observability across three pillars:

1. **Structured Logging (JSON)**:
   - All logs emitted as JSON for machine parsing
   - Automatic correlation IDs link logs across async boundaries
   - Per-request context variables avoid parameter threading

2. **Prometheus Metrics**:
   - Expose metrics on `/metrics` endpoint (port 8001)
   - Track HTTP requests, inference latency, queue depth, controller sync
   - Use percentiles (p50/p95/p99) instead of averages to detect tail latencies
   - Bounded cardinality to prevent memory exhaustion

3. **Correlation IDs**:
   - Each request gets unique ID via HTTP header or auto-generated
   - ID flows through all logs for that request
   - Workers include ID in job metadata for end-to-end tracing

**Rationale**

**Structured Logging**:
- JSON is machine-parseable, enabling aggregation in ELK/Loki/Splunk
- Correlation IDs enable finding all logs for a single user request
- Context variables (not thread-local) work with async/await
- JSON schema can be validated in tests

**Prometheus Metrics**:
- Prometheus is industry standard for Kubernetes monitoring
- Percentiles reveal tail latencies (p99 matters for user experience)
- PULL model (Prometheus scrapes) is more reliable than PUSH
- Minimal performance overhead

**Correlation IDs**:
- Standard in distributed tracing (W3C Trace Context)
- Enables request journey from ingress → API → worker → inference engine
- Even without full distributed tracing (OpenTelemetry), this helps debugging

**Trade-offs**:

- JSON logging is slightly more verbose than text (5-10% overhead)
- Metrics collection in-memory (no persistent storage, resets on restart)
- Cardinality management required (use wildcards in queries, not labels)

**Implementation Details**

### JSON Logging

```python
from app.observability import get_logger, set_correlation_id

logger = get_logger(__name__)

# Set correlation ID from HTTP header
set_correlation_id(request.headers.get("X-Correlation-ID", uuid.uuid4()))

# Log with automatic correlation ID
logger.info("Processing request", extra={"deployment": "gpt2"})
# Output:
# {"timestamp": "...", "level": "INFO", "message": "Processing request",
#  "correlation_id": "550e8400-...", "deployment": "gpt2"}
```

### Prometheus Metrics

Exposed on `http://api:8001/metrics`:

```
kernexys_http_requests_total{method="GET",path="/health",status="200"} 1234
kernexys_http_request_duration_seconds_p95{method="GET",path="/health",status="200"} 0.025
kernexys_inference_latency_seconds_p99{deployment="default/gpt2"} 0.234
kernexys_async_queue_depth{deployment="default/gpt2"} 15
kernexys_kubernetes_sync_errors_total{deployment="gpt2"} 2
```

### Alerting Examples

```yaml
# High error rate
- alert: HighErrorRate
  expr: rate(kernexys_http_requests_total{status!="200"}[5m]) > 0.05
  for: 5m

# Queue backlog
- alert: AsyncQueueBacklog
  expr: max(kernexys_async_queue_depth) > 100
  for: 10m
```

### Integration Points

- **Middleware**: Tracks HTTP request metrics (count, latency, status)
- **Routes**: Logs significant events (deployment created, model registered)
- **Worker**: Tracks inference latency, queue errors
- **Controller**: Tracks reconciliation latency and errors
- **Main**: Initializes metrics collector, adds metrics endpoint

**Consequences**

**Benefits**:
- Root cause analysis possible in minutes instead of hours
- Tail latency visibility prevents "it works on my machine" surprises
- Alerting on meaningful signals (error rate, queue depth, sync errors)
- Standard Prometheus/Grafana tooling works out of the box

**Costs**:
- Small JSON logging overhead (measured in microseconds per log)
- Metrics memory footprint grows with label cardinality (must manage)
- Requires Prometheus + Grafana for full observability (not essential but recommended)

**Testing**:
- Unit tests validate metrics collection and JSON format
- Integration tests verify correlation IDs flow through async calls
- No e2e validation needed (metrics are informational, not behavioral)

**Migration Path**

For existing deployments:
1. Enable JSON logging (KERNEXYS_LOGGING_FORMAT=json)
2. Configure Prometheus scraping of /metrics endpoint
3. Set up Grafana dashboards (examples provided)
4. Configure alerts based on SLOs

Structured logging can be toggled via environment variable.

**Related Decisions**

- ADR 0006: Defense-in-depth security (metrics require network policy exceptions)
- ADR 0005: Redis-backed inference (worker metrics track queue health)

**References**

- Prometheus: https://prometheus.io/
- W3C Trace Context: https://www.w3.org/TR/trace-context/
- OpenTelemetry: https://opentelemetry.io/ (future enhancement)
- JSON Logging: https://www.kartar.net/2015/12/structured-logging/
