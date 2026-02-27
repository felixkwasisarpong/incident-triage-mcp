import importlib
import os
from unittest.mock import patch

from incident_triage_mcp.config import load_config


def test_import_package_without_airflow_dependency() -> None:
    pkg = importlib.import_module("incident_triage_mcp")
    assert pkg is not None


def test_load_config_without_airflow_env_when_fs_backend() -> None:
    env = {
        "DEPLOYMENT_PROFILE": "local",
        "WORKFLOW_BACKEND": "none",
        "EVIDENCE_BACKEND": "fs",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = load_config()

    assert cfg.workflow_backend == "none"
    assert cfg.evidence_backend == "fs"


def test_load_config_without_airflow_env_when_none_backend() -> None:
    env = {
        "DEPLOYMENT_PROFILE": "local",
        "WORKFLOW_BACKEND": "none",
        "EVIDENCE_BACKEND": "none",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = load_config()

    assert cfg.workflow_backend == "none"
    assert cfg.evidence_backend == "none"
