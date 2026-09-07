# Kernexys documentation

This directory documents the system that exists in the repository today. The
README provides the shortest route to a local run; the guides below explain
component contracts, deployment workflows, and design rationale in more depth.

## Start here

| Guide | Use it for |
| --- | --- |
| [Local development](development.md) | Installing dependencies, configuration, migrations, and tests |
| [Architecture](architecture.md) | Control flow, ownership boundaries, and dependency failure behavior |
| [Local kind environment](kind.md) | Building and validating the complete stack on a local cluster |
| [CI/CD](cicd.md) | Understanding GitHub Actions checks and image publication |

## Components and operations

| Guide | Scope |
| --- | --- |
| [Controller](controller.md) | Reconciliation, ownership, status conditions, and envtest |
| [Deployment API and CLI](deployments.md) | Creating, inspecting, rolling back, and deleting deployments |
| [Reference runtime](runtime.md) | Runtime contract, version pinning, probes, and inference |
| [Asynchronous inference](async-inference.md) | Redis job lifecycle, backpressure, recovery, and result expiry |
| [KEDA autoscaling](keda.md) | Optional event-driven worker scaling |
| [Observability](observability.md) | Logs, request IDs, metrics, and operational signals |
| [Security](security.md) | Threat model, validation, RBAC, and network controls |

## Architecture decisions

Major choices are recorded in [`adr/`](adr/):

1. [`ModelDeployment` as the source of truth](adr/0001-modeldeployment-source-of-truth.md)
2. [Component language boundaries](adr/0002-component-languages.md)
3. [PostgreSQL registry boundary](adr/0003-postgresql-registry-boundary.md)
4. [OCI model runtime images](adr/0004-oci-model-runtime-images.md)
5. [Redis asynchronous inference](adr/0005-redis-async-inference.md)
6. [Defense-in-depth security](adr/0006-defense-in-depth-security.md)
7. [Structured observability](adr/0007-structured-observability.md)
8. [GitHub Actions CI/CD](adr/0008-github-actions-cicd.md)

Documentation should describe verified behavior. Future plans belong in an
issue or roadmap and should not be presented as implemented functionality.
