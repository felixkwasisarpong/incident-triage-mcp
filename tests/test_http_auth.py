from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from incident_triage_mcp.policy.http_auth import (
    HTTPAuthError,
    verify_api_key,
    verify_jwt_from_headers,
)


def _b64url_json(value: dict[str, object]) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sign_hs256(payload: dict[str, object], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url_json(header)
    payload_b64 = _b64url_json(payload)
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{header_b64}.{payload_b64}.{signature_b64}"


class TestHTTPAuth(unittest.TestCase):
    def test_verify_api_key_accepts_x_api_key(self) -> None:
        out = verify_api_key({"X-API-KEY": "secret-key", "X-Client-Id": "gateway"}, "secret-key")
        self.assertTrue(out["authenticated"])
        self.assertEqual(out["principal"], "gateway")

    def test_verify_api_key_accepts_bearer_token(self) -> None:
        out = verify_api_key({"Authorization": "Bearer secret-key"}, "secret-key")
        self.assertTrue(out["authenticated"])
        self.assertEqual(out["principal"], "api-key-client")

    def test_verify_api_key_rejects_invalid_key(self) -> None:
        with self.assertRaises(HTTPAuthError):
            verify_api_key({"x-api-key": "wrong"}, "secret-key")

    def test_verify_jwt_from_headers_success(self) -> None:
        now = int(time.time())
        token = _sign_hs256(
            {
                "sub": "incident-gateway",
                "iss": "incident-auth",
                "aud": "incident-triage-mcp",
                "exp": now + 120,
                "nbf": now - 5,
            },
            "jwt-secret",
        )
        out = verify_jwt_from_headers(
            {"Authorization": f"Bearer {token}"},
            "jwt-secret",
            issuer="incident-auth",
            audience="incident-triage-mcp",
            leeway_seconds=5,
        )
        self.assertTrue(out["authenticated"])
        self.assertEqual(out["principal"], "incident-gateway")

    def test_verify_jwt_from_headers_rejects_expired(self) -> None:
        now = int(time.time())
        token = _sign_hs256(
            {
                "sub": "incident-gateway",
                "iss": "incident-auth",
                "aud": "incident-triage-mcp",
                "exp": now - 120,
            },
            "jwt-secret",
        )
        with self.assertRaises(HTTPAuthError):
            verify_jwt_from_headers(
                {"authorization": f"Bearer {token}"},
                "jwt-secret",
                issuer="incident-auth",
                audience="incident-triage-mcp",
                leeway_seconds=5,
            )


if __name__ == "__main__":
    unittest.main()
