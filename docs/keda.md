# KEDA Autoscaling for Async Inference Workers

## Overview

Kernexys uses KEDA (Kubernetes Event Driven Autoscaling) to automatically scale
async inference workers based on the Redis queue depth. Workers scale up when
inference jobs are queued and scale down when the queue is empty.

## Architecture

### Scaling Signal

KEDA monitors the `kernexys:inference:queued` Redis list, which holds job IDs
waiting for processing. The length of this list is the scaling metric.

**List Length → Replica Count Mapping**:
- 0-4 jobs: 1 replica (minimum)
- 5-9 jobs: 2 replicas
- 10-19 jobs: 3-4 replicas
- 20+ jobs: Up to 10 replicas (maximum)

Each worker processes up to 4 jobs concurrently (configurable), so the scaling
math is:

```
desired_replicas = ceil(queue_depth / 4)
clamped to [1, 10]
```

### Worker Deployment

Workers run in the `kernexys-workers` namespace with:
- **Minimal permissions**: Service account with no cluster-admin rights
- **Resource requests**: 500m CPU, 256Mi memory (minimum)
- **Resource limits**: 1000m CPU, 512Mi memory (maximum)
- **Security context**: Non-root user, read-only filesystem, dropped capabilities
- **Graceful shutdown**: 35-second termination grace period

### Scale-Out

When the queue depth exceeds the threshold:
1. KEDA detects the list length increase (every 15 seconds)
2. New worker replicas are requested from Kubernetes
3. Pods start and perform recovery (requeue any stale processing-list IDs)
4. Recovery lease prevents scale-out from reclaiming active jobs
5. New workers begin processing immediately

### Scale-Down

When the queue empties:
1. KEDA reduces replica count (after 30-second cooldown)
2. Existing workers finish active jobs before graceful termination
3. No acknowledgement of unfinished work (jobs return to queue)
4. Termination waits up to 35 seconds (configured in container lifecycle)

## Configuration

### Required Secrets

The deployment requires a secret with Redis connection details:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kernexys-redis
  namespace: kernexys-workers
type: Opaque
stringData:
  url: "redis://:password@redis.kernexys-system:6379/0"
  password: "password"
```

### KEDA Settings

Edit `controller/config/worker/keda.yaml`:

- **minReplicaCount**: Minimum workers (default: 1)
- **maxReplicaCount**: Maximum workers (default: 10)
- **listLength**: Queue jobs per replica (default: 5)
- **pollingInterval**: Seconds between KEDA checks (default: 15)
- **cooldownPeriod**: Seconds before scale-down (default: 30)

### Worker Settings

Edit `controller/config/worker/deployment.yaml`:

- **KERNEXYS_ASYNC_WORKER_CONCURRENCY**: Jobs per worker (default: 4)
- **KERNEXYS_ASYNC_INFERENCE_TIMEOUT_SECONDS**: Job timeout (default: 30)
- **KERNEXYS_LOG_LEVEL**: Logging level (default: INFO)

## Deployment

### Prerequisites

- KEDA 2.12+ must be installed in the cluster
- Redis must be accessible at `redis.kernexys-system:6379`
- Controller must have created the `kernexys-workers` namespace

### Install

```bash
kubectl apply -k controller/config/worker/
```

### Verify

Check that workers are running:

```bash
kubectl get pods -n kernexys-workers
kubectl get hpa -n kernexys-workers  # KEDA creates HPA internally
```

Check KEDA status:

```bash
kubectl get scaledobject -n kernexys-workers
kubectl describe scaledobject kernexys-worker -n kernexys-workers
```

Monitor scaling activity:

```bash
kubectl logs -n kernexys-workers -f -l app=kernexys-worker
```

## Failure Scenarios

### Redis Unavailable

Workers continue to run but cannot claim new jobs. Queue fills up.
When Redis recovers, workers resume processing.

### KEDA Unavailable

Replica count remains at current level. Manual scaling required:

```bash
kubectl scale deployment kernexys-worker -n kernexys-workers --replicas=5
```

### Graceful Shutdown

When workers are terminated (scale-down or pod eviction):
1. Signal handler sets a stop event
2. Worker loop exits after finishing the current job
3. No acknowledgement sent for incomplete work
4. Job returns to processing list for recovery on restart

### Worker Failure

If a worker pod crashes:
1. Worker doesn't acknowledge the job
2. Job ID remains in processing list
3. Next worker recovery moves it back to queued
4. Job is reprocessed

## Performance Tuning

### Queue Responsiveness

Lower `pollingInterval` and `cooldownPeriod` for faster scaling:

```yaml
pollingInterval: 5
cooldownPeriod: 10
```

Lower `listLength` scales up more aggressively:

```yaml
listLength: 2  # Scale up at 2 jobs per replica
```

### Resource Efficiency

Increase `maxReplicaCount` if you have cluster capacity:

```yaml
maxReplicaCount: 20
```

Increase `minReplicaCount` if you expect consistent background load:

```yaml
minReplicaCount: 3
```

### Stability vs Responsiveness

The current defaults (15s polling, 30s cooldown) balance:
- **Stability**: Avoid thrashing (frequent scale-up/down)
- **Responsiveness**: Handle burst load within 45 seconds

Increase cooldown if you see excessive scaling:

```yaml
cooldownPeriod: 60
```

## Observability

Monitor worker performance with:

```bash
# Queue depth (number of pending jobs)
redis-cli LLEN kernexys:inference:queued

# Processing jobs (jobs being worked on)
redis-cli LLEN kernexys:inference:processing

# Job completion rate
kubectl logs -n kernexys-workers -f -l app=kernexys-worker | grep "async_inference"
```

Set up Prometheus scraping from worker pods (annotations in deployment):

```yaml
prometheus.io/scrape: "true"
prometheus.io/port: "8001"
```

## Limitations

1. **Docker/kind required**: KEDA autoscaling validation requires a real Kubernetes cluster.
   Static configuration validation only has been performed.

2. **Redis-dependent**: Queue depth scaling assumes Redis is accessible.
   If Redis is down, KEDA cannot scale (workers won't claim jobs anyway).

3. **No exactly-once semantics**: At-least-once delivery means jobs can be
   reprocessed. Ensure model inference operations are safe for this.

4. **Simple scaling signal**: Uses list length only. Does not account for
   job complexity or worker CPU usage.
