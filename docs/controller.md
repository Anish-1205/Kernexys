# ModelDeployment controller

## API surface

`platform.kernexys.io/v1alpha1` defines a namespaced `ModelDeployment` with a
small synchronous-runtime desired state:

- model name and immutable version identity;
- OCI runtime image and HTTP port;
- one to 100 fixed replicas;
- container resource requests and limits.

The CRD applies defaults for one replica and port `8080`, validates names,
versions, image length, replica bounds, and port bounds, and exposes the status
subresource. Runtime validation also rejects whitespace in image references,
negative resources, and a request larger than its matching limit.

Autoscaling and rollout strategy fields are deliberately absent from v1alpha1
until their KEDA and progressive-delivery slices define concrete behavior.

## Reconciliation contract

For each CR, the controller creates or repairs a same-name Deployment and Service
and sets the CR as their controller owner. The workload receives model identity
through environment variables, HTTP startup/liveness/readiness probes, rolling
update bounds, requested resources, and a restricted pod/container security
context. The Service exposes port 80 and targets the named runtime HTTP port.

Reconciliation treats controller-managed child fields as authoritative. It
preserves Kubernetes-assigned Service fields such as ClusterIP, but replaces
drifted workload settings. A pre-existing same-name object without a controller
owner is rejected instead of silently adopted. Kubernetes garbage collection is
responsible for children when the CR is deleted, so there is no finalizer.

Cluster-wide RBAC is limited to watching ModelDeployments, reconciling their
Deployments and Services, and updating status. Leader-election Lease access is a
separate namespaced Role rather than a cluster-wide permission.

Conditions follow Kubernetes conventions:

- `Available` reports whether every desired replica for the current Deployment
  generation is available;
- `Progressing` reports convergence in progress;
- `Degraded` distinguishes invalid desired state or a reconcile failure.

`activeModel` and `activeVersion` change only after the current workload is fully
available. Transient client failures are returned to controller-runtime for
work-queue retry/backoff. Invalid desired state is recorded and returns without a
retry loop; a spec update creates a new watch event.

## Generate and test

Generated deep-copy, CRD, and RBAC files are committed. Regenerate and validate:

```bash
make controller-generate
make controller-format
make controller-vet
make controller-test
make controller-integration
```

The unit suite covers first and repeated reconciliation, restart, drift, missing
children, invalid state, ready status, transient errors, ownership conflicts, and
deletion handling. Envtest verifies CRD defaulting/validation and reconciliation
against real kube-apiserver and etcd binaries. Actual garbage collection and the
full kubectl-to-ready-runtime path require the kind E2E workflow and have not run
on the current host.
