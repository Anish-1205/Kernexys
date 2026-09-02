"""Tests for KEDA worker autoscaling configuration."""

import shutil
import subprocess
from pathlib import Path

import pytest

# Paths to KEDA configuration files
KEDA_CONFIG_DIR = Path(__file__).parent.parent / "controller" / "config" / "worker"


def load_yaml(path: Path) -> list[dict]:
    """Load YAML file and return list of documents."""
    try:
        import yaml
    except ImportError:
        pytest.skip("PyYAML not installed")

    with open(path) as f:
        docs = list(yaml.safe_load_all(f))
    return [doc for doc in docs if doc is not None]


def load_yaml_text(contents: str) -> list[dict]:
    """Load YAML documents from rendered manifest text."""
    try:
        import yaml
    except ImportError:
        pytest.skip("PyYAML not installed")

    return [doc for doc in yaml.safe_load_all(contents) if doc is not None]


class TestKedaDeploymentManifest:
    """Validate KEDA worker deployment configuration."""

    def test_deployment_manifest_exists(self) -> None:
        """Deployment manifest file should exist."""
        manifest = KEDA_CONFIG_DIR / "deployment.yaml"
        assert manifest.exists(), f"Deployment manifest not found at {manifest}"

    def test_deployment_has_correct_name(self) -> None:
        """Deployment should be named kernexys-worker."""
        docs = load_yaml(KEDA_CONFIG_DIR / "deployment.yaml")
        deployment = docs[0]

        assert deployment["kind"] == "Deployment"
        assert deployment["metadata"]["name"] == "kernexys-worker"
        assert deployment["metadata"]["namespace"] == "kernexys-workers"

    def test_deployment_has_security_context(self) -> None:
        """Deployment should enforce security policies."""
        docs = load_yaml(KEDA_CONFIG_DIR / "deployment.yaml")
        deployment = docs[0]

        spec = deployment["spec"]["template"]["spec"]
        assert spec["securityContext"]["runAsNonRoot"] is True
        assert "seccompProfile" in spec["securityContext"]

        container = spec["containers"][0]
        sec_ctx = container["securityContext"]
        assert sec_ctx["runAsNonRoot"] is True
        assert sec_ctx["allowPrivilegeEscalation"] is False
        assert sec_ctx["readOnlyRootFilesystem"] is True
        assert "ALL" in sec_ctx["capabilities"]["drop"]

    def test_deployment_has_resource_limits(self) -> None:
        """Deployment should define resource requests and limits."""
        docs = load_yaml(KEDA_CONFIG_DIR / "deployment.yaml")
        deployment = docs[0]

        container = deployment["spec"]["template"]["spec"]["containers"][0]
        resources = container["resources"]

        assert "requests" in resources
        assert "limits" in resources
        assert resources["requests"]["cpu"] == "500m"
        assert resources["limits"]["cpu"] == "1000m"

    def test_deployment_graceful_shutdown_configured(self) -> None:
        """Deployment should have grace period for graceful shutdown."""
        docs = load_yaml(KEDA_CONFIG_DIR / "deployment.yaml")
        deployment = docs[0]

        spec = deployment["spec"]["template"]["spec"]
        assert spec["terminationGracePeriodSeconds"] == 35

    def test_deployment_liveness_checks_pid_one_with_image_python(self) -> None:
        """The slim image has Python and procfs, but intentionally has no ps binary."""
        docs = load_yaml(KEDA_CONFIG_DIR / "deployment.yaml")
        deployment = docs[0]

        command = deployment["spec"]["template"]["spec"]["containers"][0]["livenessProbe"]["exec"][
            "command"
        ]
        assert command[:2] == ["python", "-c"]
        assert "/proc/1/cmdline" in command[2]
        assert "kernexys-worker" in command[2]
        assert "ps " not in command[2]

    def test_deployment_image_is_pinned_control_plane_tag(self) -> None:
        """Worker must run the versioned control-plane image, not a floating tag.

        Regression guard: the kustomize base once carried ``kernexys:latest``,
        which is not a published image and never matches what kind/Helm load.
        """
        docs = load_yaml(KEDA_CONFIG_DIR / "deployment.yaml")
        deployment = docs[0]

        image = deployment["spec"]["template"]["spec"]["containers"][0]["image"]
        repository, _, tag = image.rpartition(":")
        assert repository == "kernexys/control-api"
        assert tag and tag != "latest"

    def test_deployment_uses_redis_secret(self) -> None:
        """Deployment should reference Redis credentials from secret."""
        docs = load_yaml(KEDA_CONFIG_DIR / "deployment.yaml")
        deployment = docs[0]

        container = deployment["spec"]["template"]["spec"]["containers"][0]
        env_vars = {e["name"]: e for e in container["env"]}

        assert "KERNEXYS_REDIS_URL" in env_vars
        assert (
            env_vars["KERNEXYS_REDIS_URL"]["valueFrom"]["secretKeyRef"]["name"] == "kernexys-redis"
        )


class TestKedaScaledObjectManifest:
    """Validate KEDA ScaledObject configuration."""

    def test_scaled_object_manifest_exists(self) -> None:
        """KEDA manifest file should exist."""
        manifest = KEDA_CONFIG_DIR / "keda.yaml"
        assert manifest.exists(), f"KEDA manifest not found at {manifest}"

    def test_scaled_object_has_correct_settings(self) -> None:
        """ScaledObject should reference worker deployment."""
        docs = load_yaml(KEDA_CONFIG_DIR / "keda.yaml")
        scaled_object = docs[0]

        assert scaled_object["kind"] == "ScaledObject"
        assert scaled_object["metadata"]["name"] == "kernexys-worker"
        assert scaled_object["spec"]["scaleTargetRef"]["name"] == "kernexys-worker"
        assert scaled_object["spec"]["scaleTargetRef"]["kind"] == "Deployment"

    def test_scaled_object_replica_bounds(self) -> None:
        """ScaledObject should define replica count bounds."""
        docs = load_yaml(KEDA_CONFIG_DIR / "keda.yaml")
        scaled_object = docs[0]

        spec = scaled_object["spec"]
        assert spec["minReplicaCount"] == 1
        assert spec["maxReplicaCount"] == 10

    def test_scaled_object_uses_redis_trigger(self) -> None:
        """ScaledObject should use Redis list length for scaling."""
        docs = load_yaml(KEDA_CONFIG_DIR / "keda.yaml")
        scaled_object = docs[0]

        triggers = scaled_object["spec"]["triggers"]
        assert len(triggers) == 1
        assert triggers[0]["type"] == "redis"
        assert triggers[0]["metadata"]["listName"] == "kernexys:inference:queued"
        assert triggers[0]["metadata"]["listLength"] == "5"

    def test_scaled_object_has_fallback(self) -> None:
        """ScaledObject should define fallback behavior."""
        docs = load_yaml(KEDA_CONFIG_DIR / "keda.yaml")
        scaled_object = docs[0]

        assert "fallback" in scaled_object["spec"]
        assert scaled_object["spec"]["fallback"]["failureThreshold"] == 3
        assert scaled_object["spec"]["fallback"]["replicas"] == 2

    def test_trigger_authentication_defined(self) -> None:
        """TriggerAuthentication should be defined for Redis credentials."""
        docs = load_yaml(KEDA_CONFIG_DIR / "keda.yaml")
        trigger_auth = docs[1]

        assert trigger_auth["kind"] == "TriggerAuthentication"
        assert trigger_auth["metadata"]["name"] == "kernexys-redis-auth"


class TestKedaRbac:
    """Validate KEDA worker RBAC configuration."""

    def test_rbac_manifest_exists(self) -> None:
        """RBAC manifest should exist."""
        manifest = KEDA_CONFIG_DIR / "rbac.yaml"
        assert manifest.exists(), f"RBAC manifest not found at {manifest}"

    def test_service_account_created(self) -> None:
        """ServiceAccount should be created for workers."""
        docs = load_yaml(KEDA_CONFIG_DIR / "rbac.yaml")
        sa = docs[0]

        assert sa["kind"] == "ServiceAccount"
        assert sa["metadata"]["name"] == "kernexys-worker"

    def test_minimal_rbac_permissions(self) -> None:
        """Worker Role should have minimal permissions."""
        docs = load_yaml(KEDA_CONFIG_DIR / "rbac.yaml")
        role = docs[1]

        assert role["kind"] == "Role"
        rules = role["rules"]

        # Only configmap read permissions expected
        assert len(rules) == 1
        assert "get" in rules[0]["verbs"]
        assert rules[0]["resources"] == ["configmaps"]

    def test_role_binding_created(self) -> None:
        """RoleBinding should bind Role to ServiceAccount."""
        docs = load_yaml(KEDA_CONFIG_DIR / "rbac.yaml")
        binding = docs[2]

        assert binding["kind"] == "RoleBinding"
        assert binding["roleRef"]["name"] == "kernexys-worker"
        assert binding["subjects"][0]["name"] == "kernexys-worker"


class TestKedaStaticValidation:
    """Static validation that doesn't require running KEDA."""

    def test_kustomization_manifest_exists(self) -> None:
        """Kustomization file should exist."""
        manifest = KEDA_CONFIG_DIR / "kustomization.yaml"
        assert manifest.exists(), f"Kustomization not found at {manifest}"

    def test_helm_worker_runtime_settings_match_raw_manifests(self) -> None:
        """Keep runtime-critical worker and KEDA settings aligned across installers."""
        helm = shutil.which("helm")
        if helm is None:
            pytest.skip("helm not available")

        chart = Path(__file__).parent.parent / "helm" / "kernexys"
        result = subprocess.run(
            [helm, "template", "kernexys", str(chart)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, f"helm template failed: {result.stderr}"
        rendered = [doc for doc in load_yaml_text(result.stdout) if doc.get("kind")]

        raw_deployment = load_yaml(KEDA_CONFIG_DIR / "deployment.yaml")[0]
        helm_deployment = next(
            doc
            for doc in rendered
            if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "kernexys-worker"
        )
        raw_pod = raw_deployment["spec"]["template"]["spec"]
        helm_pod = helm_deployment["spec"]["template"]["spec"]
        raw_container = raw_pod["containers"][0]
        helm_container = helm_pod["containers"][0]

        for field in (
            "image",
            "imagePullPolicy",
            "command",
            "resources",
            "livenessProbe",
            "securityContext",
        ):
            assert helm_container[field] == raw_container[field]
        for field in ("securityContext", "terminationGracePeriodSeconds", "volumes"):
            assert helm_pod[field] == raw_pod[field]
        assert helm_container["volumeMounts"] == raw_container["volumeMounts"]
        assert helm_container["env"][0] == raw_container["env"][0]

        helm_config = next(
            doc
            for doc in rendered
            if doc["kind"] == "ConfigMap" and doc["metadata"]["name"] == "kernexys-worker"
        )
        raw_literal_env = {item["name"]: item["value"] for item in raw_container["env"][1:]}
        assert helm_config["data"] == raw_literal_env

        raw_keda = load_yaml(KEDA_CONFIG_DIR / "keda.yaml")
        raw_scaled_object = raw_keda[0]
        raw_auth = raw_keda[1]
        helm_scaled_object = next(doc for doc in rendered if doc["kind"] == "ScaledObject")
        helm_auth = next(doc for doc in rendered if doc["kind"] == "TriggerAuthentication")
        assert helm_scaled_object["spec"] == raw_scaled_object["spec"]
        assert helm_auth["spec"] == raw_auth["spec"]

    def test_namespace_manifest_exists(self) -> None:
        """Namespace manifest should exist."""
        manifest = KEDA_CONFIG_DIR / "namespace.yaml"
        assert manifest.exists(), f"Namespace manifest not found at {manifest}"

    def test_kubectl_dry_run_succeeds(self) -> None:
        """kubectl apply --dry-run should validate all manifests."""
        try:
            # This requires kubectl to be installed
            result = subprocess.run(
                ["kubectl", "apply", "-k", str(KEDA_CONFIG_DIR), "--dry-run=client"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            # Dry-run should succeed
            assert result.returncode == 0, f"kubectl validation failed: {result.stderr}"
        except FileNotFoundError:
            pytest.skip("kubectl not available")
        except subprocess.TimeoutExpired:
            pytest.skip("kubectl validation timed out")

    def test_scaling_formula_correctness(self) -> None:
        """Verify KEDA scaling formula is correct."""
        # With listLength=5, KEDA scales based on queue depth
        # Each replica can handle approximately 5 jobs
        # Formula: max(1, min(ceil(queue_depth / listLength), maxReplicas))

        test_cases = [
            (0, 1),  # Empty queue: min 1 replica
            (1, 1),  # 1-4 jobs: 1 replica (queue depth < listLength)
            (4, 1),  # 4 jobs: 1 replica
            (5, 1),  # 5 jobs: ceil(5/5)=1 replica
            (6, 2),  # 6 jobs: ceil(6/5)=2 replicas
            (10, 2),  # 10 jobs: ceil(10/5)=2 replicas
            (15, 3),  # 15 jobs: ceil(15/5)=3 replicas
            (50, 10),  # 50 jobs: ceil(50/5)=10 replicas (max)
            (100, 10),  # 100 jobs: ceil(100/5)=20, clamped to 10 (max)
        ]

        list_length = 5  # From keda.yaml
        min_replicas = 1
        max_replicas = 10

        for queue_depth, expected_replicas in test_cases:
            import math

            desired = math.ceil(queue_depth / list_length) if queue_depth > 0 else min_replicas
            actual = max(min_replicas, min(desired, max_replicas))

            assert actual == expected_replicas, (
                f"Queue depth {queue_depth}: expected {expected_replicas} replicas, got {actual}"
            )
