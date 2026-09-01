# Local kind environment

Kernexys pins kind `v0.33.0` and its Kubernetes node image to a digest-backed
Kubernetes `v1.37.0` build. Required host tools are Docker, kind, and kubectl.
The checked-in cluster configuration creates one control-plane and one worker.

Create the cluster and load locally built first-party images without a registry:

```bash
make kind-create
make kind-build
make kind-load
make kind-install
make kind-validate
```

Delete the cluster with `make kind-delete`. The command is scoped to the
`kernexys` kind cluster by default; override `KIND_CLUSTER_NAME` consistently if
another name is required.

The image defaults are `kernexys/control-api:dev` and
`kernexys/controller:dev`. kind imports those images directly from the local
Docker daemon, so GHCR credentials are not part of local development.

## Validation status

The kind workflow has not been executed on the current host because Docker, kind,
and kubectl are absent. A successful controller unit test does not count as kind
E2E validation. The exact first command required on a capable host is:

```bash
make kind-create
```
