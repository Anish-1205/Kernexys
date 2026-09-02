from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER_RBAC = ROOT / "controller" / "config" / "rbac"


def test_event_recording_is_limited_to_controller_namespace() -> None:
    role = yaml.safe_load((CONTROLLER_RBAC / "leader_election_role.yaml").read_text())
    event_rules = [
        rule
        for rule in role["rules"]
        if rule["apiGroups"] == [""] and rule["resources"] == ["events"]
    ]

    assert role["kind"] == "Role"
    assert role["metadata"]["namespace"] == "kernexys-system"
    assert event_rules == [
        {"apiGroups": [""], "resources": ["events"], "verbs": ["create", "patch"]}
    ]


def test_cluster_role_does_not_grant_event_access() -> None:
    cluster_role = yaml.safe_load((CONTROLLER_RBAC / "role.yaml").read_text())

    assert not any("events" in rule["resources"] for rule in cluster_role["rules"])
