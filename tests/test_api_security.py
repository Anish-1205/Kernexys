"""Tests for Kernexys API deployment security configuration."""

from pathlib import Path

import pytest

# Paths to API configuration files
API_CONFIG_DIR = Path(__file__).parent.parent / "controller" / "config" / "api"


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
        deployment = [d for d in docs if d.get("kind") == "Deployment"][0]
        
        spec = deployment["spec"]["template"]["spec"]
        assert spec["securityContext"]["runAsNonRoot"] is True
        assert spec["securityContext"]["fsReadOnlyRootFilesystem"] is True
        assert spec["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"

    def test_deployment_container_security(self) -> None:
        """Container should have strict security constraints."""
        docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        deployment = [d for d in docs if d.get("kind") == "Deployment"][0]
        
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        sec_ctx = container["securityContext"]
        
        assert sec_ctx["runAsNonRoot"] is True
        assert sec_ctx["allowPrivilegeEscalation"] is False
        assert "ALL" in sec_ctx["capabilities"]["drop"]

    def test_deployment_has_resource_limits(self) -> None:
        """API should have resource requests and limits."""
        docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        deployment = [d for d in docs if d.get("kind") == "Deployment"][0]
        
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        resources = container["resources"]
        
        assert resources["requests"]["cpu"] == "250m"
        assert resources["requests"]["memory"] == "256Mi"
        assert resources["limits"]["cpu"] == "1000m"
        assert resources["limits"]["memory"] == "512Mi"

    def test_deployment_has_health_checks(self) -> None:
        """API should define liveness and readiness probes."""
        docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        deployment = [d for d in docs if d.get("kind") == "Deployment"][0]
        
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        assert "livenessProbe" in container
        assert "readinessProbe" in container
        assert container["livenessProbe"]["httpGet"]["path"] == "/health/live"
        assert container["readinessProbe"]["httpGet"]["path"] == "/health/ready"

    def test_deployment_anti_affinity(self) -> None:
        """API pods should prefer to run on different nodes."""
        docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        deployment = [d for d in docs if d.get("kind") == "Deployment"][0]
        
        affinity = deployment["spec"]["template"]["spec"]["affinity"]
        assert "podAntiAffinity" in affinity
        assert "preferredDuringSchedulingIgnoredDuringExecution" in affinity["podAntiAffinity"]

    def test_deployment_uses_secrets(self) -> None:
        """Deployment should reference database and Redis from secrets."""
        docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        deployment = [d for d in docs if d.get("kind") == "Deployment"][0]
        
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        env_vars = {e["name"]: e for e in container["env"]}
        
        assert "KERNEXYS_DATABASE_URL" in env_vars
        assert env_vars["KERNEXYS_DATABASE_URL"]["valueFrom"]["secretKeyRef"]["name"] == "kernexys-db"
        assert "KERNEXYS_REDIS_URL" in env_vars
        assert env_vars["KERNEXYS_REDIS_URL"]["valueFrom"]["secretKeyRef"]["name"] == "kernexys-redis"

    def test_service_created(self) -> None:
        """Service should expose API on port 8000."""
        docs = load_yaml(API_CONFIG_DIR / "deployment.yaml")
        service = [d for d in docs if d.get("kind") == "Service"][0]
        
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
        sa = [d for d in docs if d.get("kind") == "ServiceAccount"][0]
        
        assert sa["metadata"]["name"] == "kernexys-api"
        assert sa["metadata"]["namespace"] == "kernexys-system"

    def test_cluster_role_permissions(self) -> None:
        """ClusterRole should have appropriate permissions."""
        docs = load_yaml(API_CONFIG_DIR / "rbac.yaml")
        role = [d for d in docs if d.get("kind") == "ClusterRole"][0]
        
        rules = role["rules"]
        assert len(rules) >= 3  # At least 3 rule groups
        
        # Check for model deployment permissions (resource and status subresource)
        all_resources = []
        for rule in rules:
            all_resources.extend(rule.get("resources", []))
        
        assert any("modeldeployments" in r for r in all_resources)

    def test_cluster_role_binding_created(self) -> None:
        """ClusterRoleBinding should bind role to service account."""
        docs = load_yaml(API_CONFIG_DIR / "rbac.yaml")
        binding = [d for d in docs if d.get("kind") == "ClusterRoleBinding"][0]
        
        assert binding["roleRef"]["name"] == "kernexys-api"
        assert binding["subjects"][0]["name"] == "kernexys-api"


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
        
        api_policy = [p for p in nps if p["metadata"]["name"] == "kernexys-api"][0]
        
        assert "Ingress" in api_policy["spec"]["policyTypes"]
        assert len(api_policy["spec"]["ingress"]) > 0

    def test_network_policy_restricts_egress(self) -> None:
        """NetworkPolicy should restrict outbound traffic."""
        docs = load_yaml(API_CONFIG_DIR / "networkpolicy.yaml")
        nps = [d for d in docs if d.get("kind") == "NetworkPolicy"]
        
        api_policy = [p for p in nps if p["metadata"]["name"] == "kernexys-api"][0]
        
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
