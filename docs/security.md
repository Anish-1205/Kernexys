# Kernexys Security Hardening

Kernexys implements defense-in-depth security across control plane deployment,
API server, and async workers. This document describes the security features
and how to configure them.

## Deployment Security

### Pod Security Standards

All namespaces enforce Kubernetes Pod Security Standards at the "restricted"
level, which enforces:

- Non-root users
- Read-only root filesystem
- Dropped Linux capabilities
- No privilege escalation
- Limited seccomp profiles

### API Deployment

The API deployment (`controller/config/api/deployment.yaml`) includes:

- **Security Context**:
  - Runs as non-root user (uid 65534 / nobody)
  - Read-only root filesystem with tmpfs for temporary data
  - Drops all Linux capabilities
  - seccomp profile set to RuntimeDefault

- **Resource Management**:
  - Requests: 250m CPU, 256Mi memory (for scheduling)
  - Limits: 1000m CPU, 512Mi memory (for containment)
  - Prevents resource starvation attacks

- **Health Checks**:
  - Liveness probe: `/health/live` (detects deadlocks)
  - Readiness probe: `/health/ready` (detects startup issues)
  - Automatic restart on failure

- **Pod Topology**:
  - Pod anti-affinity distributes API replicas across nodes
  - Prevents single-node failures
  - Two replicas for high availability

### Worker Deployment

The async worker deployment (`controller/config/worker/deployment.yaml`)
applies similar security hardening:

- Non-root user, read-only filesystem, dropped capabilities
- Resource limits prevent worker pods from consuming cluster resources
- Graceful 35-second shutdown period for job completion
- Health checks monitor worker availability

## RBAC (Role-Based Access Control)

### API Permissions

The API ServiceAccount (`kernexys-api`) has ClusterRole permissions to:

- Read/write ModelDeployment resources and status
- Read Kubernetes Deployments and Services for status monitoring
- Read Endpoints for service discovery

Permissions are minimal and follow principle of least privilege.

### Worker Permissions

The worker ServiceAccount (`kernexys-worker`) has minimal permissions:
- Read configmaps (for potential future feature flags)

Workers do not manage Kubernetes resources directly.

## Network Policies

### API Network Policy

Restricts API pod network traffic:

**Ingress**:
- From Ingress controller on port 8000 (HTTP traffic)
- From monitoring namespace on port 8001 (Prometheus scraping)

**Egress**:
- To kube-dns for service discovery (DNS)
- To PostgreSQL for database access
- To Redis for async queue operations
- To Kubernetes API for resource management
- To worker pods for queue operations (future)

### Default Deny

The namespace has a default-deny NetworkPolicy that blocks all traffic except
what is explicitly allowed above. This prevents data exfiltration and lateral
movement.

## Secrets Management

### Required Secrets

Create the following secrets before deploying:

```bash
# PostgreSQL connection
kubectl create secret generic kernexys-db \
  --from-literal=url='postgresql+asyncpg://user:pass@host:5432/db' \
  -n kernexys-system

# Redis connection (with password)
kubectl create secret generic kernexys-redis \
  --from-literal=url='redis://:password@host:6379/0' \
  --from-literal=password='password' \
  -n kernexys-system

# KEDA Redis authentication
kubectl create secret generic kernexys-redis-auth \
  --from-literal=password='password' \
  -n kernexys-workers
```

### Secret Best Practices

1. Use external secret operators (e.g., External Secrets Operator, Sealed Secrets)
   to manage secrets safely in GitOps workflows
2. Rotate database and Redis passwords regularly
3. Use least-privilege database users
4. Enable encryption at rest for secrets
5. Audit secret access

## Rate Limiting

Future: API rate limiting can be implemented via:

1. **Ingress controller**: Global rate limits at entry point
2. **Middleware**: Application-level rate limiting per user/IP
3. **Redis-backed**: Distributed rate limiting for multi-instance API

Recommended configuration:
- 100 requests/minute per IP for unauthenticated endpoints
- 1000 requests/minute per authenticated user
- Async job submission: 10 jobs/minute per deployment

## Secrets Scanning

Before deployment, scan for secrets in the codebase:

```bash
# Using git-secrets
git secrets --scan

# Using truffleHog
truffleHog git https://github.com/your-repo

# Using detect-secrets
detect-secrets scan --baseline .secrets.baseline
```

## Container Security Scanning

Scan container images for vulnerabilities:

```bash
# Using Trivy
trivy image kernexys:latest

# Using Grype
grype kernexys:latest
```

## Pod Security Policy (Deprecated)

**Note**: PodSecurityPolicy is deprecated in Kubernetes 1.25+. Use Pod Security
Standards instead (configured via namespace labels).

For older clusters, a PSP can be created:

```yaml
apiVersion: policy/v1beta1
kind: PodSecurityPolicy
metadata:
  name: kernexys-restricted
spec:
  privileged: false
  allowPrivilegeEscalation: false
  requiredDropCapabilities:
    - ALL
  volumes:
    - 'configMap'
    - 'emptyDir'
  hostNetwork: false
  hostPID: false
  hostIPC: false
  runAsUser:
    rule: 'MustRunAsNonRoot'
  fsGroup:
    rule: 'RunAsAny'
  readOnlyRootFilesystem: true
```

## SecurityContext Summary

All containers use:

```yaml
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 65534  # nobody
  seccompProfile:
    type: RuntimeDefault
```

## Audit Logging

Enable Kubernetes audit logging to track access to resources:

```yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
- level: Metadata
  resources:
  - group: "platform.kernexys.io"
    resources: ["modeldeployments"]
  - group: "apps"
    resources: ["deployments"]
- level: Metadata
  verbs: ["create", "update", "patch", "delete"]
```

## TLS/HTTPS

### Ingress TLS

Configure TLS certificates via Ingress:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: kernexys-api
  namespace: kernexys-system
spec:
  tls:
  - hosts:
    - api.example.com
    secretName: api-tls-cert
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: kernexys-api
            port:
              number: 8000
```

### Internal Service-to-Service

For internal communication (API to database/Redis), use network policies
instead of mTLS to keep configuration simple while maintaining isolation.

## Compliance

Kernexys security configuration aligns with:

- **NIST Cybersecurity Framework**: Identify, Protect, Detect, Respond, Recover
- **CIS Kubernetes Benchmarks**: V1.6.0
- **Kubernetes Security Best Practices**: Pod security, RBAC, network policies

## Security Checklist

Before production deployment:

- [ ] All images scanned for vulnerabilities
- [ ] Secrets stored in secure backend (not in Git)
- [ ] Pod Security Standards enforced via namespace labels
- [ ] NetworkPolicies restrict all traffic by default
- [ ] RBAC configured with least privilege
- [ ] Resource limits prevent resource exhaustion
- [ ] Audit logging enabled
- [ ] TLS/HTTPS configured for external access
- [ ] Database and Redis passwords rotated
- [ ] Container registry access restricted
- [ ] Image pull secrets configured

## Incident Response

In case of security incident:

1. **Isolate affected pods**: Delete compromised pods
2. **Review audit logs**: Determine scope of access
3. **Rotate secrets**: Database and Redis passwords
4. **Rebuild images**: If code is suspected compromised
5. **Scan cluster**: For lateral movement
6. **Post-mortem**: Document root cause and improvements
