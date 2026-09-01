# Kernexys Observability

Kernexys provides comprehensive observability through structured logging,
Prometheus metrics, and correlation IDs for request tracing.

## Structured Logging

### JSON Logging Format

By default, all logs are in JSON format for easy parsing and aggregation:

```json
{
  "timestamp": "2025-01-01 12:00:00,123",
  "level": "INFO",
  "logger": "app.routes",
  "message": "Registry sync completed",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Log Levels

Configure via `KERNEXYS_LOG_LEVEL` environment variable:

- `DEBUG`: Verbose application state (development only)
- `INFO`: Major operations (default)
- `WARNING`: Recoverable issues
- `ERROR`: Unrecoverable errors that require attention
- `CRITICAL`: System failures

### Correlation IDs

Each request gets a unique correlation ID that flows through all logs:

```python
# Log with automatic correlation ID
logger = get_logger(__name__)
logger.info("Starting inference", extra={"deployment": "gpt2"})
# Output:
# {
#   "level": "INFO",
#   "message": "Starting inference",
#   "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
#   "deployment": "gpt2"
# }
```

## Prometheus Metrics

### Endpoint

Metrics are exposed on `http://api:8001/metrics` in Prometheus exposition format.

### HTTP Request Metrics

**kernexys_http_requests_total**
- Type: Counter
- Labels: `method`, `path`, `status`
- Description: Total HTTP requests processed
- Example:
  ```
  kernexys_http_requests_total{method="POST",path="/deployments",status="201"} 42
  ```

**kernexys_http_request_duration_seconds_p50/p95/p99**
- Type: Histogram (percentiles)
- Labels: `method`, `path`, `status`
- Description: HTTP request latency (50th, 95th, 99th percentiles)
- Example:
  ```
  kernexys_http_request_duration_seconds_p50{method="POST",path="/registry/models",status="200"} 0.015
  kernexys_http_request_duration_seconds_p95{method="POST",path="/registry/models",status="200"} 0.087
  kernexys_http_request_duration_seconds_p99{method="POST",path="/registry/models",status="200"} 0.234
  ```

### Inference Metrics

**kernexys_inference_latency_seconds_p50/p95/p99**
- Type: Histogram (percentiles)
- Labels: `deployment`
- Description: Inference request latency
- Example:
  ```
  kernexys_inference_latency_seconds_p50{deployment="default/gpt2"} 0.542
  kernexys_inference_latency_seconds_p95{deployment="default/gpt2"} 1.234
  kernexys_inference_latency_seconds_p99{deployment="default/gpt2"} 2.891
  ```

### Async Queue Metrics

**kernexys_async_queue_depth**
- Type: Gauge
- Labels: `deployment`
- Description: Current number of pending inference jobs
- Example:
  ```
  kernexys_async_queue_depth{deployment="default/gpt2"} 15
  ```

**kernexys_async_queue_errors_total**
- Type: Counter
- Labels: `deployment`, `type`
- Description: Async queue error count
- Example:
  ```
  kernexys_async_queue_errors_total{deployment="default/gpt2",type="timeout"} 3
  kernexys_async_queue_errors_total{deployment="default/gpt2",type="redis_unavailable"} 1
  ```

### Model Registry Metrics

**kernexys_model_deployments_total**
- Type: Gauge
- Description: Total model deployments in the cluster
- Example:
  ```
  kernexys_model_deployments_total 8
  ```

**kernexys_model_versions_total**
- Type: Gauge
- Description: Total model versions in the registry
- Example:
  ```
  kernexys_model_versions_total 23
  ```

### Kubernetes Controller Metrics

**kernexys_kubernetes_sync_duration_seconds_p50/p95/p99**
- Type: Histogram (percentiles)
- Labels: `deployment`
- Description: Controller reconciliation latency
- Example:
  ```
  kernexys_kubernetes_sync_duration_seconds_p50{deployment="gpt2"} 0.125
  kernexys_kubernetes_sync_duration_seconds_p95{deployment="gpt2"} 0.456
  kernexys_kubernetes_sync_duration_seconds_p99{deployment="gpt2"} 1.234
  ```

**kernexys_kubernetes_sync_errors_total**
- Type: Counter
- Labels: `deployment`
- Description: Controller reconciliation error count
- Example:
  ```
  kernexys_kubernetes_sync_errors_total{deployment="gpt2"} 2
  ```

## Prometheus Configuration

### Scrape Configuration

Add to your Prometheus `prometheus.yml`:

```yaml
scrape_configs:
- job_name: 'kernexys-api'
  static_configs:
  - targets: ['kernexys-api.kernexys-system:8001']
  scrape_interval: 30s
  scrape_timeout: 10s
```

### Kubernetes ServiceMonitor

For Prometheus Operator:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kernexys-api
  namespace: kernexys-system
spec:
  selector:
    matchLabels:
      component: control-api
  endpoints:
  - port: metrics
    interval: 30s
```

## Example Prometheus Queries

### API Latency (P95)

```promql
kernexys_http_request_duration_seconds_p95{path="/registry/models", status="200"}
```

### Inference Throughput

```promql
rate(kernexys_http_requests_total{path="/deployments/.+/infer", status="200"}[5m])
```

### Async Queue Backlog

```promql
sum by (deployment) (kernexys_async_queue_depth)
```

### Error Rate

```promql
rate(kernexys_http_requests_total{status!="200", status!="201"}[5m])
```

### Controller Reconciliation Success Rate

```promql
(
  sum by (deployment) (rate(kernexys_kubernetes_sync_duration_seconds_p50[5m]))
  /
  sum by (deployment) (rate(kernexys_kubernetes_sync_errors_total[5m]) + rate(kernexys_kubernetes_sync_duration_seconds_p50[5m]))
) * 100
```

## Alert Rules

### High API Error Rate

```yaml
alert: KernexysHighErrorRate
expr: rate(kernexys_http_requests_total{status!="200", status!="201"}[5m]) > 0.05
for: 5m
annotations:
  summary: "High error rate detected in Kernexys API"
  description: "Error rate is {{ $value | humanizePercentage }}"
```

### Async Queue Backlog

```yaml
alert: KernexysAsyncQueueBacklog
expr: max(kernexys_async_queue_depth) > 100
for: 10m
annotations:
  summary: "Async queue has high backlog"
  description: "Queue depth is {{ $value }} jobs"
```

### Controller Reconciliation Failures

```yaml
alert: KernexysControllerErrors
expr: rate(kernexys_kubernetes_sync_errors_total[5m]) > 0
for: 5m
annotations:
  summary: "Controller reconciliation failing"
  description: "{{ $value }} errors per second"
```

## Grafana Dashboards

### Create Dashboard

1. Add Prometheus data source: `http://prometheus:9090`
2. Create new dashboard
3. Add panels using queries from above

### Recommended Panels

- **API Latency**: P50/P95/P99 line graph over time
- **Throughput**: Request rate by endpoint (stacked area)
- **Error Rate**: Failed requests as percentage (gauge)
- **Async Queue**: Queue depth gauge by deployment
- **Model Deployments**: Total count gauge
- **Controller Health**: Sync duration and error rate

## Best Practices

### Logging

1. Use appropriate log levels:
   - DEBUG for variable values during development
   - INFO for major state changes
   - WARNING for recoverable issues
   - ERROR for failures requiring action

2. Include relevant context:
   ```python
   logger.info("Deployment created", extra={
       "deployment_name": name,
       "namespace": namespace,
       "duration_seconds": duration
   })
   ```

3. Avoid logging sensitive data:
   - No passwords, API keys, or credentials
   - No PII (personally identifiable information)
   - No large binary data

### Metrics

1. Keep cardinality bounded:
   - Max 10 labels per metric
   - Avoid high-cardinality fields (user IDs, full paths)
   - Use wildcards in queries instead

2. Use appropriate metric types:
   - Counter: cumulative values (requests, errors, bytes)
   - Gauge: point-in-time values (queue depth, memory usage)
   - Histogram: latencies and sizes (request duration)

3. Name metrics clearly:
   - `<component>_<noun>_<unit>`
   - Example: `kernexys_http_requests_total`

## Troubleshooting

### Missing Metrics

1. Check if metrics endpoint is accessible:
   ```bash
   curl http://kernexys-api:8001/metrics
   ```

2. Verify Prometheus scrape config:
   ```bash
   curl http://prometheus:9090/api/v1/targets
   ```

3. Check pod annotations:
   ```bash
   kubectl get pods -n kernexys-system -o json | grep prometheus
   ```

### Correlation ID Not in Logs

1. Verify it's set in middleware:
   ```bash
   curl -H "X-Correlation-ID: test-123" http://kernexys-api:8000/registry/models
   ```

2. Check observability module is loaded in main.py

3. Verify `KERNEXYS_LOGGING_CORRELATION_ID_ENABLED=true`

### High Cardinality Metrics

Use Prometheus relabel rules to drop high-cardinality labels:

```yaml
scrape_configs:
- job_name: 'kernexys-api'
  metric_relabel_configs:
  - source_labels: [__name__]
    regex: 'kernexys_http_request_duration.*'
    target_label: path
    replacement: 'redacted'  # Drop individual paths
```
