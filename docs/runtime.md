# Reference model runtime

Kernexys includes a deliberately small CPU-only sentiment classifier so the full
platform can demonstrate deployment, update, rollback, metrics, and failure
behavior without a GPU or external model service. It is deterministic and is not
presented as a model-quality benchmark.

## Artifact identity

`runtime/Dockerfile` accepts `MODEL_VERSION=v1` or `v2`. That value is baked into
`KERNEXYS_BAKED_MODEL_VERSION`; the controller supplies the declared model
version as `KERNEXYS_MODEL_VERSION`. A mismatch fails process configuration at
startup instead of serving the wrong weights under a requested version.

For local kind, Make builds and loads:

```text
kernexys/model-runtime:v1
kernexys/model-runtime:v2
```

Mutable tags are local-development conveniences. Registry records already accept
OCI digests, which should identify release artifacts outside the local workflow.

## HTTP contract

- `GET /health/live` checks the process only.
- `GET /health/ready` reports loaded model identity.
- `POST /v1/infer` accepts `{"text":"..."}` with a one-to-4096-character text.
- `GET /metrics` exposes Prometheus text format.

Bodies are capped independently of schema validation. Uvicorn concurrency,
keep-alive, and graceful-shutdown bounds are environment configurable. Safe
caller request IDs are echoed; invalid or missing IDs are replaced.

The first metrics are:

- `kernexys_inference_requests_total{model,version,outcome}`;
- `kernexys_inference_duration_seconds{model,version}`;
- `kernexys_runtime_info{model,version}`.

## Version behavior

Both versions use the same logistic scoring code with fixed in-image weights.
`v2` adds vocabulary including `reliable`, `fast`, `stable`, `flaky`, and `slow`,
which provides a controlled output change for update and canary demonstrations.

## Validation status

Unit/API tests exercise both classifiers, image-version mismatch handling,
health/readiness, successful and invalid inference, request-size backpressure,
correlation, and metrics. A real Uvicorn process was started locally using `v2`,
became ready, returned positive inference for `reliable and fast`, exposed the
counter metric, and was stopped. Docker image builds and Kubernetes runtime
behavior remain unverified because Docker and kind are absent from this host.
