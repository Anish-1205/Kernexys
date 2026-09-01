# ADR 0006: Defense-in-Depth Security Architecture

**Status**: Accepted

**Date**: 2025-01-XX

**Context**

Kernexys runs model inference workloads in a Kubernetes cluster with sensitive
customer models and data. The system must protect against:

- Unauthorized access to models or inference data
- Resource starvation attacks that disable the platform
- Lateral movement within the cluster
- Data exfiltration via network traffic
- Privilege escalation within containers
- Supply chain attacks via container images

Kubernetes provides native security primitives (RBAC, NetworkPolicies,
PodSecurityPolicy), but they require explicit configuration. The default
Kubernetes deployment is not secure for production.

**Decision**

Implement defense-in-depth security across three layers:

1. **Pod-level Security**:
   - All pods run as non-root users (uid 65534)
   - Read-only root filesystem with tmpfs for temporary data
   - All Linux capabilities dropped (CAP_ALL)
   - seccomp profile set to RuntimeDefault
   - Resource limits prevent resource starvation

2. **Kubernetes-level Access Control**:
   - ClusterRoles with minimal permissions (principle of least privilege)
   - Separate ServiceAccounts for API, workers, controller
   - Pod Security Standards enforce "restricted" level across namespaces
   - Default-deny NetworkPolicies restrict all traffic by default

3. **Cluster-level Network Isolation**:
   - Explicit NetworkPolicies define allowed ingress/egress
   - API only receives traffic from ingress controller
   - Workers only receive traffic from API
   - Database and Redis connections encrypted (via TLS in future)
   - DNS resolution via kube-dns only

**Rationale**

- **Non-root execution**: Containers compromised via image vulnerability cannot
  gain full system access. Prevents container escape exploitation.

- **Read-only filesystem**: Malicious code cannot persist changes or write to
  host filesystem. Forces attacks to operate in-memory only.

- **Dropped capabilities**: Removes kernel features unnecessary for
  applications (network/filesystem/process management). Minimizes kernel attack
  surface.

- **Least-privilege RBAC**: Each component gets minimum permissions needed.
  Compromised API cannot delete controller resources or scale workers.

- **NetworkPolicies**: Even if a pod is compromised, network policies prevent
  lateral movement to other pods or external networks.

- **Resource limits**: Prevents one misbehaving pod from consuming cluster
  resources and crashing other workloads.

This layered approach means an attacker must bypass multiple security
mechanisms to succeed. No single misconfiguration or vulnerability is fatal.

**Implementation Details**

### API Deployment Security

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 65534
  fsReadOnlyRootFilesystem: true
  seccompProfile:
    type: RuntimeDefault
  capabilities:
    drop: ["ALL"]

resources:
  requests:
    cpu: 250m
    memory: 256Mi
  limits:
    cpu: 1000m
    memory: 512Mi
```

### RBAC

API ServiceAccount permissions limited to:
- Read/write ModelDeployment resources
- Read Deployment/Service status
- No write access to system resources

Worker ServiceAccount permissions limited to:
- Read configmaps (future: feature flags)
- No Kubernetes resource management

### NetworkPolicies

```yaml
ingress:
- from: [ingress-nginx namespace]  # HTTP traffic from ingress controller
- from: [monitoring namespace]      # Prometheus metrics scraping

egress:
- to: [kube-dns]                    # DNS resolution
- to: [PostgreSQL pod]              # Database access
- to: [Redis pod]                   # Async queue
- to: [Kubernetes API]              # Resource management
```

Default-deny policy blocks all other traffic.

**Consequences**

**Benefits**:
- Significantly increases attack cost even if container is compromised
- Aligns with Kubernetes security best practices
- Enables compliance with security frameworks (CIS, NIST)
- Fail-safe: new deployments are secure by default

**Costs**:
- More complex Kubernetes manifest files (18 security-related fields)
- Requires explicit secret management (cannot embed in env vars)
- NetworkPolicies require cluster support (CNI with network policy support)
- Testing requires valid Kubernetes cluster (cannot test with Docker)
- Breaking changes: Any code trying to write to filesystem will fail

**Migration Path**

For existing deployments:
1. Create security-hardened manifests alongside existing ones
2. Gradually migrate workloads to hardened manifests
3. Monitor for breakages in application code
4. Once validated, deprecate old manifests

**Exceptions**

Allow exceptions only with explicit justification:
- Databases (PostgreSQL/Redis) may run as root if operator doesn't support
  non-root (document exception)
- If a third-party service requires elevated privileges, isolate to separate
  namespace with relaxed policies

**Testing**

- Unit tests validate YAML structure (security fields present)
- Integration tests verify pod startup with restrictions
- E2E tests verify functionality under security constraints
- Continuous vulnerability scanning via container scan tools

**Related Decisions**

- ADR 0005: Redis-backed at-least-once delivery (async inference)
- ADR 0004: OCI model runtime images (sandboxed model execution)

**References**

- Kubernetes Security Best Practices: https://kubernetes.io/docs/concepts/security/
- CIS Kubernetes Benchmarks: https://www.cisecurity.org/
- NIST Cybersecurity Framework: https://www.nist.gov/cyberframework
