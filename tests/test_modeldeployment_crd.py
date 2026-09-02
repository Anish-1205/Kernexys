from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CRD_PATH = (
    ROOT
    / "controller"
    / "config"
    / "crd"
    / "bases"
    / "platform.kernexys.io_modeldeployments.yaml"
)


def test_modeldeployment_requires_root_spec() -> None:
    crd = yaml.safe_load(CRD_PATH.read_text())
    schema = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]

    assert "spec" in schema["required"]
