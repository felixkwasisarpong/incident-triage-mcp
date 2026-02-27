import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "spec" / "evidence-bundle.v1.schema.json"
VALID_EXAMPLE_PATH = ROOT / "examples" / "evidence" / "INC-123.v1.json"
INVALID_EXAMPLE_PATH = ROOT / "examples" / "evidence" / "INVALID.v1.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator() -> Draft202012Validator:
    schema = _load_json(SCHEMA_PATH)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_valid_evidence_bundle_example_matches_v1_schema() -> None:
    validator = _validator()
    example = _load_json(VALID_EXAMPLE_PATH)

    errors = sorted(validator.iter_errors(example), key=lambda e: list(e.path))
    assert not errors


def test_invalid_evidence_bundle_example_fails_v1_schema() -> None:
    validator = _validator()
    example = _load_json(INVALID_EXAMPLE_PATH)

    errors = list(validator.iter_errors(example))

    assert errors
    assert any(error.validator in {"required", "type", "const"} for error in errors)
