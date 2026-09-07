# Contributing to Kernexys

Thank you for improving Kernexys. Keep changes focused, preserve the ownership
boundaries in [`docs/architecture.md`](docs/architecture.md), and update the
relevant documentation when behavior or configuration changes.

## Development setup

Kernexys requires Python 3.11+, Go, and—depending on the test—a local Docker or
Kubernetes installation. Install the Python development environment with:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

On PowerShell, use `.venv\Scripts\python.exe` and the corresponding executables
under `.venv\Scripts`. See the [development guide](docs/development.md) for
database configuration and component-specific setup.

## Validation

Run the checks that cover the area you changed:

```bash
make lint
make test
make controller-format
make controller-vet
make controller-test
make runtime-lint
make runtime-test
```

Integration checks require their named external dependencies. The envtest,
Redis, API/Kubernetes, kind, and Helm workflows are documented in
[`docs/`](docs/README.md).

Changes to `controller/api/v1alpha1/modeldeployment_types.go` must be followed
by `make controller-generate`; include the regenerated deepcopy, CRD, and RBAC
artifacts in the same commit.

## Pull requests

- Use a focused branch and a descriptive conventional commit where practical.
- Add or update tests for behavior changes.
- Document new configuration, API behavior, failure modes, and operational
  requirements.
- Never commit `.env` files, credentials, kubeconfigs, build outputs, or local
  test artifacts.
- Explain validation performed and any checks that could not be run.

By submitting a contribution, you confirm that you have the right to contribute
it to this repository.
