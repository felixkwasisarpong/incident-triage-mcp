from __future__ import annotations

import hashlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from incident_triage_mcp.policy.safe_actions import SafeActionContext, SafeActionError, enforce


def _ctx(**overrides: object) -> SafeActionContext:
    payload = {
        "tool_name": "jira.create_ticket",
        "role": "responder",
        "dry_run": False,
        "reason": "Create production incident ticket",
        "confirm_token": "token-one",
        "idempotency_key": "INC-123-SCRUM-1",
    }
    payload.update(overrides)
    return SafeActionContext(**payload)


class TestSafeActions(unittest.TestCase):
    def test_dry_run_bypasses_enforcement(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            enforce(_ctx(dry_run=True, reason=None, confirm_token=None, idempotency_key=None))

    def test_rejects_when_no_approval_token_configured(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SafeActionError) as ctx:
                enforce(_ctx())
        self.assertIn("No approval token configured", str(ctx.exception))

    def test_accepts_legacy_confirm_token(self) -> None:
        with patch.dict(os.environ, {"CONFIRM_TOKEN": "token-one"}, clear=True):
            enforce(_ctx(confirm_token="token-one"))

    def test_accepts_confirm_tokens_csv(self) -> None:
        with patch.dict(os.environ, {"CONFIRM_TOKENS": "token-alpha, token-one, token-beta"}, clear=True):
            enforce(_ctx(confirm_token="token-one"))

    def test_accepts_sha256_token(self) -> None:
        token = "secret-token"
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with patch.dict(os.environ, {"CONFIRM_TOKEN_SHA256": digest}, clear=True):
            enforce(_ctx(confirm_token=token))

    def test_rejects_wrong_confirm_token(self) -> None:
        with patch.dict(os.environ, {"CONFIRM_TOKEN": "token-one"}, clear=True):
            with self.assertRaises(SafeActionError) as ctx:
                enforce(_ctx(confirm_token="wrong-token"))
        self.assertIn("confirm_token", str(ctx.exception))

    def test_rejects_non_dry_run_without_idempotency_key(self) -> None:
        with patch.dict(os.environ, {"CONFIRM_TOKEN": "token-one"}, clear=True):
            with self.assertRaises(SafeActionError) as ctx:
                enforce(_ctx(idempotency_key=None))
        self.assertIn("idempotency_key", str(ctx.exception))

    def test_rejects_short_idempotency_key(self) -> None:
        with patch.dict(os.environ, {"CONFIRM_TOKEN": "token-one"}, clear=True):
            with self.assertRaises(SafeActionError) as ctx:
                enforce(_ctx(idempotency_key="short"))
        self.assertIn("at least 8 characters", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
