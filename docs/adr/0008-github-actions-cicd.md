# ADR 0008: GitHub Actions CI/CD Pipeline

**Status**: Accepted

**Date**: 2025-01-XX

**Context**

Kernexys is a multi-language project (Python API, Go controller, Python runtime).
Manual testing and deployment is error-prone and doesn't scale. The project
needs automated validation to:

- Catch bugs before they reach main branch
- Ensure code meets quality standards (lint, types, tests)
- Build and publish container images consistently
- Validate Kubernetes manifests before deployment
- Detect security vulnerabilities early

Without CI/CD, code quality degrades quickly and deployment becomes risky.

**Decision**

Implement GitHub Actions CI/CD pipeline with:

1. **Per-language workflows**:
   - Python API: lint, type-check, test, security scan
   - Go Controller: lint, test, vet, build
   - Each language gets tailored checks

2. **Container build pipeline**:
   - Build images for API, controller, runtime
   - Push to GitHub Container Registry (GHCR)
   - Security scanning with Trivy

3. **Kubernetes validation**:
   - Helm chart linting and templating
   - Kind cluster E2E tests on every push

4. **Workflow triggers**:
   - Python CI: on changes to app/**, tests/**, pyproject.toml
   - Go CI: on changes to controller/**
   - Container build: after code CI passes on main
   - E2E: on every push/PR, full cluster validation
   - Helm: on changes to helm/**

**Rationale**

**Per-language workflows**:
- Python and Go have different tooling (pytest vs go test, ruff vs golangci-lint)
- Separate workflows make it easy to update tools independently
- Clear separation of concerns (API team owns Python, platform team owns Go)

**GitHub Actions**:
- Native integration with GitHub (no external service)
- Community actions marketplace for common tasks
- Free tier sufficient for open-source projects
- Branch protection rules enforce passing checks

**GHCR** (instead of Docker Hub):
- Native GitHub integration (OAuth via GITHUB_TOKEN)
- Free private registries for all repositories
- Built-in vulnerability scanning
- No monthly cost

**Kind for E2E**:
- Kubernetes-in-Docker runs in GitHub Actions runners
- Full cluster validation without cloud resources
- Catches manifest issues that unit tests miss
- Relatively fast (5-10 minutes)

**Trade-offs**:

- GitHub Actions pricing after free tier (120 CPU minutes/month)
- Kind doesn't test actual cloud features (ingress, load balancers)
- Container scanning is informational only (doesn't block)

**Implementation Details**

### Workflow Files

```
.github/workflows/
├── python-ci.yml          # Python lint, type-check, test
├── go-ci.yml              # Go lint, test, vet, build
├── container-build.yml    # Build and push container images
├── helm-validate.yml      # Helm chart validation
└── e2e-tests.yml          # Kind cluster E2E tests
```

### Execution Flow

```
Push to feature branch
  ↓
Python CI + Go CI (parallel)
  ↓
Pass? → Run on push to main
  ↓
Container Build (if on main)
  ↓
Helm Validate
  ↓
E2E Tests on kind
```

### Job Dependencies

Jobs run in parallel unless explicitly dependent via
`needs: [job1, job2]`. This minimizes total workflow time.

### Image Tags

- Branch pushes: `ghcr.io/user/kernexys/api:main-<sha>`
- Release tags: `ghcr.io/user/kernexys/api:v1.0.0`
- Both pushed to GHCR

### Caching Strategy

- pip dependencies: `~/.cache/pip`
- Go modules: `~/go/pkg/mod`
- Docker layers: GitHub Actions Cache API
- Cache invalidated on: `go.mod`, `requirements*.txt` changes

**Consequences**

**Benefits**:
- Code quality enforced automatically
- Deployment errors caught before production
- Consistent builds across developers
- Security scanning integrated into pipeline
- Type safety catches Python bugs early
- Container images always built and tested

**Costs**:
- GitHub Actions runner time consumed (but free tier is generous)
- Workflow configuration requires YAML expertise
- E2E tests add 5-10 minutes to merge time
- Debugging failures requires looking at GitHub Actions logs

**Testing**:
- Workflows tested by running them on PRs
- Test failures are obvious (red X in GitHub)
- No separate testing needed for CI/CD itself

**Migration Path**

For existing repository:
1. Create `.github/workflows/` directory
2. Add Python CI workflow
3. Add Go CI workflow
4. Enable branch protection (require passing checks)
5. Add container build on main merge
6. Add E2E tests gradually

**Related Decisions**

- ADR 0006: Security hardening (container scanning)
- ADR 0007: Observability (metrics in tests)

**Future Enhancements**

1. **Release automation**: semantic-release for automatic versioning
2. **Slack notifications**: workflow status to Slack channel
3. **CodeQL**: GitHub's code scanning for security
4. **Renovate**: automatic dependency updates
5. **ArgoCD**: automatic deployment to production
6. **Load testing**: k6 tests in CI pipeline

**References**

- GitHub Actions: https://docs.github.com/en/actions
- GitHub Container Registry: https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- Kind: https://kind.sigs.k8s.io/
- Helm: https://helm.sh/
- Trivy: https://github.com/aquasecurity/trivy
