import importlib
import os
from unittest.mock import patch

from incident_triage_mcp.config import load_config


def test_import_works_without_airflow_environment_variables() -> None:
    with patch.dict(os.environ, {}, clear=True):
        module = importlib.import_module("incident_triage_mcp")

    assert module is not None


def test_load_config_works_in_standalone_fs_mode_without_airflow_env() -> None:
    env = {
        "DEPLOYMENT_PROFILE": "local",
        "WORKFLOW_BACKEND": "none",
        "EVIDENCE_BACKEND": "fs",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = load_config()

    assert cfg.workflow_backend == "none"
    assert cfg.evidence_backend == "fs"
    assert cfg.airflow_base_url is None
    assert cfg.airflow_username is None
    assert cfg.airflow_password is None
