# Kernexys CI/CD Pipeline

Kernexys uses GitHub Actions for continuous integration and deployment.
The pipeline ensures code quality, security, and reliability through
automated testing, linting, container builds, and deployment validation.

## Workflow Overview

```
Push to main/feature branch
  ↓
├─→ Python CI (lint, type-check, test)
├─→ Go CI (lint, test, vet, build)
└─→ Manual review on PR

On merge to main:
  ↓
├─→ Python CI
├─→ Go CI
├─→ Container Build & Push (to GHCR)
├─→ Helm Validation
└─→ E2E Tests on kind cluster

Deploy to production (manual):
  ↓
└─→ Helm release (ArgoCD or manual)
```

## Workflows

### Python API CI (`.github/workflows/python-ci.yml`)

Runs on any push/PR affecting Python code.

**Jobs**:

1. **Lint** (`ruff check`)
   - Check style: E (errors), W (warnings), F (flakes), I (imports)
   - Format check: ensures consistent formatting
   - Runs on Python 3.11

2. **Type Check** (`mypy`)
   - Static type checking with strict mode
   - Detects type errors before runtime
   - Non-blocking (failures don't block merge)

3. **Test** (pytest)
   - PostgreSQL + Redis services for integration tests
   - Coverage reporting to Codecov
   - Runs all tests with `pytest` and `--basetemp=./tmp`
   - Required to pass for merge

4. **Security Scan**
   - Bandit: static security vulnerability scanning
   - Safety: dependency vulnerability checking
   - Non-blocking (informational)

**Running Locally**:

```bash
# Lint
ruff check app/ tests/

# Type check
mypy app/ --strict

# Test (requires Docker for services)
docker-compose up -d postgres redis
python -m pytest tests/ -v
docker-compose down
```

### Go Controller CI (`.github/workflows/go-ci.yml`)

Runs on any push/PR affecting Go code in `controller/`.

**Jobs**:

1. **Lint** (`golangci-lint`)
   - Checks style, correctness, complexity
   - Runs latest version of golangci-lint
   - Required to pass

2. **Test** (`go test`)
   - Race condition detection (`-race` flag)
   - Coverage reporting
   - All Go packages in controller/

3. **Vet** (`go vet`)
   - Static analysis for common bugs
   - Checks correctness of Go code

4. **Build**
   - Builds controller binary
   - Uploads artifact for later use

**Running Locally**:

```bash
cd controller
go mod download
go vet ./...
go test -v -race ./...
```

### Container Build (`.github/workflows/container-build.yml`)

Builds and pushes container images to GitHub Container Registry (GHCR)
when code merges to main.

**Images Built**:

1. `kernexys/api` - Control API server
2. `kernexys/controller` - Kubernetes controller
3. `kernexys/runtime` - Model runtime environment

**Features**:

- Docker Buildx for multi-platform builds
- GitHub Actions cache for faster builds
- Automatic tagging: `main-<sha>` on main, semver on releases
- Trivy security scanning for vulnerabilities
- SARIF report uploaded to GitHub Security tab

**Image Push**:

```bash
# Authenticate with GHCR
echo ${{ secrets.GITHUB_TOKEN }} | docker login ghcr.io -u ${{ github.actor }} --password-stdin

# Pull images
docker pull ghcr.io/your-org/kernexys/api:main-abc123
```

### Helm Validation (`.github/workflows/helm-validate.yml`)

Validates Helm chart on every change.

**Jobs**:

1. **Validate**
   - `helm lint`: checks syntax and best practices
   - `helm template`: renders all templates
   - `kubectl apply --dry-run`: validates manifests
   - Checks required values exist

2. **Test**
   - `helm install --dry-run`: simulates installation
   - Verifies template rendering

3. **Docs**
   - Generates README.md from chart values
   - Uses helm-docs tool

**Running Locally**:

```bash
helm lint helm/kernexys/
helm template kernexys helm/kernexys/ | kubectl apply -f - --dry-run=client
```

### Kubernetes E2E Tests (`.github/workflows/e2e-tests.yml`)

Runs end-to-end tests in a kind cluster on every push/PR.

**Steps**:

1. Create kind cluster from config
2. Build all images locally
3. Load images into kind cluster
4. Create namespaces and secrets
5. Deploy with Kustomize
6. Wait for rollout completion
7. Run integration tests
8. Collect logs and artifacts

**Test Execution**:

```bash
kind create cluster --config deploy/kind/config.yaml
kubectl apply -k controller/config/
python -m pytest tests/integration/ -v
```

**Artifacts** (on failure):

- `e2e-logs/nodes.txt`: Kubernetes node status
- `e2e-logs/pods.txt`: Pod descriptions
- `e2e-logs/api.log`: API logs
- `e2e-logs/controller.log`: Controller logs

## Secrets and Permissions

### Required GitHub Secrets

None explicitly required - GitHub Actions provides:
- `GITHUB_TOKEN`: automatic for pushing to GHCR
- `secrets.GITHUB_TOKEN`: available in all workflows

### Optional Secrets (for production)

If deploying to external registry or cloud:
- `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`: Docker Hub
- `AWS_ROLE_ARN`: AWS OIDC federation
- `SLACK_WEBHOOK`: Slack notifications

### Permissions

`.github/workflows/*.yml` sets minimal required permissions:

```yaml
permissions:
  contents: read
  packages: write  # For GHCR push
  security-events: write  # For SARIF upload
```

## Performance Characteristics

### Build Times

- Python CI: ~2-3 minutes (includes test services startup)
- Go CI: ~1-2 minutes
- Container build (with cache): ~2-5 minutes
- E2E tests: ~5-10 minutes (includes kind cluster creation)
- Total (all workflows): ~15-20 minutes

### Optimization Strategies

1. **Cache** (used in all workflows):
   - GitHub Actions cache for pip/go dependencies
   - Docker layer cache via buildx

2. **Parallelization**:
   - Lint, test, build jobs run in parallel
   - Container build runs after CI passes

3. **Early Termination**:
   - Lint failures stop test job
   - Python CI failures don't block Go CI
   - E2E tests run only on main branch

## Failure Handling

### Lint Failures

- **Impact**: Blocks merge (required check)
- **Fix**: Run locally and commit fixes
  ```bash
  ruff format app/ tests/
  git add .
  git commit -m "style: fix linting issues"
  ```

### Test Failures

- **Impact**: Blocks merge (required check)
- **Fix**: Run locally to reproduce
  ```bash
  pytest tests/test_foo.py::TestBar::test_baz -vv
  ```

### Container Build Failures

- **Impact**: Doesn't block merge (only runs on main)
- **Action**: Investigate in GitHub Actions logs
- **Fix**: Fix code and merge again, or rebuild manually
  ```bash
  docker build -f Dockerfile -t kernexys:latest .
  docker push ghcr.io/your-org/kernexys:latest
  ```

### E2E Test Failures

- **Impact**: Doesn't block merge (informational)
- **Action**: Check artifacts for logs
- **Fix**: Reproduce in local kind cluster
  ```bash
  kind create cluster --config deploy/kind/config.yaml
  kubectl apply -k controller/config/
  ```

## Deployment

### Manual Deployment (recommended)

```bash
# Using Helm
helm upgrade --install kernexys helm/kernexys/ \
  -n kernexys-system \
  --create-namespace \
  -f values.yaml

# Using kubectl
kustomize build controller/config/ | kubectl apply -f -
```

### GitOps Deployment (ArgoCD)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kernexys
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/kernexys
    targetRevision: main
    path: controller/config/
  destination:
    server: https://kubernetes.default.svc
    namespace: kernexys-system
```

## Monitoring CI/CD

### GitHub Actions Status

- View in GitHub: Settings → Actions → Workflow runs
- Workflow status badge in README
- Branch protection rules enforce passing checks

### Badges in README

```markdown
[![Python CI](https://github.com/your-org/kernexys/actions/workflows/python-ci.yml/badge.svg)](https://github.com/your-org/kernexys/actions/workflows/python-ci.yml)
[![Container Build](https://github.com/your-org/kernexys/actions/workflows/container-build.yml/badge.svg)](https://github.com/your-org/kernexys/actions/workflows/container-build.yml)
```

### Coverage Dashboard

Codecov integration (optional) shows:
- Coverage percentage over time
- Coverage by file
- Diff coverage on PRs

## Best Practices

1. **Keep workflows simple**:
   - One job per concern (lint, test, build)
   - Reuse actions from marketplace
   - Pin action versions

2. **Fail fast**:
   - Lint before tests
   - Skip expensive jobs if linting fails

3. **Cache aggressively**:
   - Cache dependencies (pip, go mod)
   - Cache Docker layers
   - Clear cache on dependency updates

4. **Document everything**:
   - Comment workflow steps
   - Document manual deployment procedures
   - Keep README updated

5. **Monitor for failures**:
   - Subscribe to workflow notifications
   - Set up Slack/email alerts
   - Review failed runs promptly

## Troubleshooting

### "No cache found" messages

Cache keys may have changed. This is normal and build will proceed.

### "Permission denied" on GHCR push

Verify `GITHUB_TOKEN` has `packages: write` permission in workflow.

### E2E test timeouts

Kind cluster startup can be slow. Increase timeout:
```yaml
timeout-minutes: 15
```

### Container image not found in kind

Ensure `kind load docker-image` command runs after build.

## Next Steps

1. Enable branch protection rules
2. Configure automatic deployments with ArgoCD
3. Add Slack notifications for workflow status
4. Set up coverage dashboards
5. Implement automated releases via semantic-release
