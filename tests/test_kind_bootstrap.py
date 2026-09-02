"""Validation for the repository-managed kind development dependencies."""

from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
DEPENDENCIES = ROOT / "deploy" / "kind" / "dependencies"


def load_yaml(path: Path) -> list[dict]:
    return [document for document in yaml.safe_load_all(path.read_text()) if document]


def test_kind_postgres_is_pinned_persistent_and_restricted() -> None:
    documents = load_yaml(DEPENDENCIES / "postgres.yaml")
    stateful_set = next(document for document in documents if document["kind"] == "StatefulSet")
    pod = stateful_set["spec"]["template"]["spec"]
    container = pod["containers"][0]

    assert container["image"] == "postgres:17.6-alpine3.22"
    assert next(item for item in container["env"] if item["name"] == "PGDATA")["value"].endswith(
        "/pgdata"
    )
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert (
        stateful_set["spec"]["volumeClaimTemplates"][0]["spec"]["resources"]["requests"]["storage"]
        == "1Gi"
    )


def test_kind_migration_job_uses_loaded_api_image_and_database_secret() -> None:
    documents = load_yaml(ROOT / "deploy" / "kind" / "migrate.yaml")
    job = next(document for document in documents if document["kind"] == "Job")
    container = job["spec"]["template"]["spec"]["containers"][0]

    assert container["image"] == "kernexys/control-api:dev"
    assert container["command"] == ["alembic", "upgrade", "head"]
    assert container["env"][0]["valueFrom"]["secretKeyRef"] == {
        "name": "kernexys-db",
        "key": "url",
    }


def test_kind_install_wires_secret_postgres_migration_and_control_plane() -> None:
    makefile = (ROOT / "Makefile").read_text()
    install = makefile.split("kind-install:", 1)[1].split("kind-validate:", 1)[0]

    assert "KERNEXYS_POSTGRES_PASSWORD is required" in install
    assert "deploy/kind/dependencies" in install
    assert "statefulset/postgres" in install
    assert "deploy/kind/migrate.yaml" in install
    assert "controller/config/default" in install


def test_default_kustomization_does_not_register_namespace_twice() -> None:
    default = (ROOT / "controller" / "config" / "default" / "kustomization.yaml").read_text()

    assert "namespace.yaml" not in default
    assert "../api" in default
