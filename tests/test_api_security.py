"""Tests for Kernexys API deployment security configuration."""

import shutil
import subprocess
from pathlib import Path

import pytest

# Paths to API configuration files
API_CONFIG_DIR = Path(__file__).parent.parent / "controller" / "config" / "api"
HELM_CHART = Path(__file__).parent.parent / "helm" / "kernexys"


def load_yaml(path: Path) -> list[dict]:
    """Load YAML file and return list of documents."""
    try:
        import yaml
    except ImportError:
        pytest.skip("PyYAML not installed")

    with open(path) as f:
        docs = list(yaml.safe_load_all(f))
    return [doc for doc in docs if doc is not None]


class TestApiDeploymentSecurity:
    """Validate API deployment security hardening."""

    def test_deployment_manifest_exists(self) -> None:
        """API deployment manifest should exist."""
        manifest = API_CONFIG_DIR / "deployment.yaml"
        assert manifest.exists()

    def test_deployment_enforces_security_context(self) -> None:
        """Deployment should enforce security policies."""
        docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        deployment = next(d for d in docs if d.get("kind") == "Deployment")

        spec = deployment["spec"]["template"]["spec"]
        assert spec["securityContext"]["runAsNonRoot"] is True
        assert spec["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"

    def test_deployment_container_security(self) -> None:
        """Container should have strict security constraints."""
        docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        deployment = next(d for d in docs if d.get("kind") == "Deployment")

        container = deployment["spec"]["template"]["spec"]["containers"][0]
        sec_ctx = container["securityContext"]

        assert sec_ctx["runAsNonRoot"] is True
        assert sec_ctx["allowPrivilegeEscalation"] is False
        assert sec_ctx["readOnlyRootFilesystem"] is True
        assert "ALL" in sec_ctx["capabilities"]["drop"]

    def test_deployment_has_resource_limits(self) -> None:
        """API should have resource requests and limits."""
        docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        deployment = next(d for d in docs if d.get("kind") == "Deployment")

        container = deployment["spec"]["template"]["spec"]["containers"][0]
        resources = container["resources"]

        assert resources["requests"]["cpu"] == "250m"
        assert resources["requests"]["memory"] == "256Mi"
        assert resources["limits"]["cpu"] == "1000m"
        assert resources["limits"]["memory"] == "512Mi"

    def test_deployment_has_health_checks(self) -> None:
        """API should define liveness and readiness probes."""
        docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        deployment = next(d for d in docs if d.get("kind") == "Deployment")

        container = deployment["spec"]["template"]["spec"]["containers"][0]
        assert "livenessProbe" in container
        assert "readinessProbe" in container
        assert container["livenessProbe"]["httpGet"]["path"] == "/health/live"
        assert container["readinessProbe"]["httpGet"]["path"] == "/health/ready"

    def test_deployment_anti_affinity(self) -> None:
        """API pods should prefer to run on different nodes."""
        docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        deployment = next(d for d in docs if d.get("kind") == "Deployment")

        affinity = deployment["spec"]["template"]["spec"]["affinity"]
        assert "podAntiAffinity" in affinity
        assert "preferredDuringSchedulingIgnoredDuringExecution" in affinity["podAntiAffinity"]

    def test_deployment_requires_only_database_in_the_default_baseline(self) -> None:
        """Disabled async inference must not require a Redis Secret."""
        docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        deployment = next(d for d in docs if d.get("kind") == "Deployment")

        container = deployment["spec"]["template"]["spec"]["containers"][0]
        env_vars = {e["name"]: e for e in container["env"]}

        assert "KERNEXYS_DATABASE_URL" in env_vars
        assert (
            env_vars["KERNEXYS_DATABASE_URL"]["valueFrom"]["secretKeyRef"]["name"] == "kernexys-db"
        )
        assert env_vars["KERNEXYS_ASYNC_INFERENCE_ENABLED"]["value"] == "false"
        assert "KERNEXYS_REDIS_URL" not in env_vars

        assert container["image"] == "kernexys/control-api:dev"

    def test_service_created(self) -> None:
        """Service should expose API on port 8000."""
        docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        service = next(d for d in docs if d.get("kind") == "Service")

        assert service["spec"]["type"] == "ClusterIP"
        assert service["spec"]["ports"][0]["port"] == 8000
        assert service["spec"]["ports"][0]["targetPort"] == "http"


class TestApiRbac:
    """Validate API RBAC configuration."""

    def test_rbac_manifest_exists(self) -> None:
        """RBAC manifest should exist."""
        manifest = API_CONFIG_DIR / "rbac.yaml"
        assert manifest.exists()

    def test_service_account_created(self) -> None:
        """ServiceAccount should be created for API."""
        docs = load_yaml(API_CONFIG_DIR / "rbac.yaml")
        sa = next(d for d in docs if d.get("kind") == "ServiceAccount")

        assert sa["metadata"]["name"] == "kernexys-api"
        assert sa["metadata"]["namespace"] == "kernexys-system"

    def test_cluster_role_permissions(self) -> None:
        """ClusterRole should permit only the current ModelDeployment gateway calls."""
        docs = load_yaml(API_CONFIG_DIR / "rbac.yaml")
        role = next(d for d in docs if d.get("kind") == "ClusterRole")

        assert role["rules"] == [
            {
                "apiGroups": ["platform.kernexys.io"],
                "resources": ["modeldeployments"],
                "verbs": ["create", "delete", "get", "patch"],
            }
        ]

    def test_api_cannot_mutate_runtime_resources(self) -> None:
        docs = load_yaml(API_CONFIG_DIR / "rbac.yaml")
        role = next(d for d in docs if d.get("kind") == "ClusterRole")

        resources = {resource for rule in role["rules"] for resource in rule.get("resources", [])}
        assert resources.isdisjoint({"deployments", "replicasets", "services", "pods"})

    def test_cluster_role_binding_created(self) -> None:
        """ClusterRoleBinding should bind role to service account."""
        docs = load_yaml(API_CONFIG_DIR / "rbac.yaml")
        binding = next(d for d in docs if d.get("kind") == "ClusterRoleBinding")

        assert binding["roleRef"]["name"] == "kernexys-api"
        assert binding["subjects"][0]["name"] == "kernexys-api"

    def test_deployment_uses_bound_service_account(self) -> None:
        deployment_docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        deployment = next(d for d in deployment_docs if d.get("kind") == "Deployment")
        rbac_docs = load_yaml(API_CONFIG_DIR / "rbac.yaml")
        binding = next(d for d in rbac_docs if d.get("kind") == "ClusterRoleBinding")

        assert deployment["spec"]["template"]["spec"]["serviceAccountName"] == "kernexys-api"
        assert binding["subjects"] == [
            {
                "kind": "ServiceAccount",
                "name": "kernexys-api",
                "namespace": "kernexys-system",
            }
        ]


def test_helm_renders_canonical_api_identity_and_rbac() -> None:
    import yaml

    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("Helm is not installed")
    rendered = subprocess.run(
        [helm, "template", "kernexys", str(HELM_CHART), "--set", "worker.enabled=false"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    docs = [document for document in yaml.safe_load_all(rendered) if document]
    api_role = next(
        document
        for document in docs
        if document.get("kind") == "ClusterRole"
        and document.get("metadata", {}).get("name") == "kernexys-api"
    )
    api_binding = next(
        document
        for document in docs
        if document.get("kind") == "ClusterRoleBinding"
        and document.get("metadata", {}).get("name") == "kernexys-api"
    )
    api_deployment = next(
        document
        for document in docs
        if document.get("kind") == "Deployment"
        and document.get("metadata", {}).get("name") == "kernexys-api"
    )

    assert api_role["rules"] == [
        {
            "apiGroups": ["platform.kernexys.io"],
            "resources": ["modeldeployments"],
            "verbs": ["create", "delete", "get", "patch"],
        }
    ]
    assert api_binding["subjects"][0]["name"] == "kernexys-api"
    assert api_deployment["spec"]["template"]["spec"]["serviceAccountName"] == "kernexys-api"
    default_env = {
        item["name"]: item
        for item in api_deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert "KERNEXYS_REDIS_URL" not in default_env


def test_helm_requires_redis_secret_when_async_inference_is_enabled() -> None:
    import yaml

    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("Helm is not installed")
    rendered = subprocess.run(
        [
            helm,
            "template",
            "kernexys",
            str(HELM_CHART),
            "--set-string",
            "api.env.ASYNC_INFERENCE_ENABLED=true",
            "--set",
            "worker.enabled=false",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    docs = [document for document in yaml.safe_load_all(rendered) if document]
    deployment = next(document for document in docs if document.get("kind") == "Deployment")
    env = {
        item["name"]: item
        for item in deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert env["KERNEXYS_REDIS_URL"]["valueFrom"]["secretKeyRef"] == {
        "name": "kernexys-redis",
        "key": "url",
    }


class TestApiNetworkPolicy:
    """Validate network security policies."""

    def test_network_policy_exists(self) -> None:
        """NetworkPolicy manifest should exist."""
        manifest = API_CONFIG_DIR / "networkpolicy.yaml"
        assert manifest.exists()

    def test_network_policy_restricts_ingress(self) -> None:
        """NetworkPolicy should restrict inbound traffic."""
        docs = load_yaml(API_CONFIG_DIR / "networkpolicy.yaml")
        nps = [d for d in docs if d.get("kind") == "NetworkPolicy"]

        api_policy = next(p for p in nps if p["metadata"]["name"] == "kernexys-api")

        assert "Ingress" in api_policy["spec"]["policyTypes"]
        assert len(api_policy["spec"]["ingress"]) > 0

    def test_network_policy_restricts_egress(self) -> None:
        """NetworkPolicy should restrict outbound traffic."""
        docs = load_yaml(API_CONFIG_DIR / "networkpolicy.yaml")
        nps = [d for d in docs if d.get("kind") == "NetworkPolicy"]

        api_policy = next(p for p in nps if p["metadata"]["name"] == "kernexys-api")

        assert "Egress" in api_policy["spec"]["policyTypes"]
        assert len(api_policy["spec"]["egress"]) > 0

    def test_default_deny_policy_exists(self) -> None:
        """Namespace should have a default-deny policy."""
        docs = load_yaml(API_CONFIG_DIR / "networkpolicy.yaml")
        nps = [d for d in docs if d.get("kind") == "NetworkPolicy"]

        deny_all = [p for p in nps if "deny-all" in p["metadata"]["name"]]
        assert len(deny_all) > 0


class TestApiNamespace:
    """Validate namespace security configuration."""

    def test_namespace_exists(self) -> None:
        """Namespace manifest should exist."""
        manifest = API_CONFIG_DIR / "namespace.yaml"
        assert manifest.exists()

    def test_namespace_enforces_pod_security(self) -> None:
        """Namespace should enforce Pod Security Policy."""
        docs = load_yaml(API_CONFIG_DIR / "namespace.yaml")
        ns = docs[0]

        labels = ns["metadata"]["labels"]
        assert labels["pod-security.kubernetes.io/enforce"] == "restricted"
        assert labels["pod-security.kubernetes.io/audit"] == "restricted"
