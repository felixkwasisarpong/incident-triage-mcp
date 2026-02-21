from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


class HTTPAuthError(PermissionError):
    pass


def _lower_headers(headers: dict[str, str]) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in headers.items()}


def _b64url_decode(raw: str) -> bytes:
    padded = raw + "=" * ((4 - (len(raw) % 4)) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _extract_bearer_token(headers: dict[str, str]) -> str:
    normalized = _lower_headers(headers)
    authorization = normalized.get("authorization", "")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPAuthError("Missing or invalid Authorization header. Expected 'Bearer <token>'.")
    token = parts[1].strip()
    if not token:
        raise HTTPAuthError("Bearer token is empty.")
    return token


def verify_api_key(headers: dict[str, str], expected_api_key: str) -> dict[str, Any]:
    normalized = _lower_headers(headers)
    provided = normalized.get("x-api-key")
    if not provided:
        try:
            provided = _extract_bearer_token(normalized)
        except HTTPAuthError:
            provided = None
    if not provided or not hmac.compare_digest(provided, expected_api_key):
        raise HTTPAuthError("Invalid API key.")
    principal = normalized.get("x-client-id", "api-key-client")
    return {"mode": "api_key", "authenticated": True, "principal": principal}


def verify_jwt_hs256(
    token: str,
    secret: str,
    *,
    issuer: str | None = None,
    audience: str | None = None,
    leeway_seconds: int = 30,
) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPAuthError("Invalid JWT format.")
    header_b64, payload_b64, signature_b64 = parts

    try:
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception as exc:
        raise HTTPAuthError("JWT decode failed.") from exc

    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise HTTPAuthError("JWT must use HS256.")
    if not isinstance(payload, dict):
        raise HTTPAuthError("JWT payload must be an object.")

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        actual = _b64url_decode(signature_b64)
    except Exception as exc:
        raise HTTPAuthError("JWT signature decode failed.") from exc
    if not hmac.compare_digest(actual, expected):
        raise HTTPAuthError("Invalid JWT signature.")

    now = int(time.time())
    if "exp" in payload:
        try:
            exp = int(payload["exp"])
        except Exception as exc:
            raise HTTPAuthError("JWT exp claim is invalid.") from exc
        if now > exp + leeway_seconds:
            raise HTTPAuthError("JWT expired.")
    if "nbf" in payload:
        try:
            nbf = int(payload["nbf"])
        except Exception as exc:
            raise HTTPAuthError("JWT nbf claim is invalid.") from exc
        if now + leeway_seconds < nbf:
            raise HTTPAuthError("JWT not active yet.")

    if issuer and payload.get("iss") != issuer:
        raise HTTPAuthError("JWT issuer mismatch.")

    if audience:
        aud = payload.get("aud")
        if isinstance(aud, list):
            ok = audience in [str(v) for v in aud]
        else:
            ok = str(aud) == audience
        if not ok:
            raise HTTPAuthError("JWT audience mismatch.")

    principal = str(payload.get("sub") or payload.get("client_id") or "jwt-client")
    return {
        "mode": "jwt_hs256",
        "authenticated": True,
        "principal": principal,
        "issuer": payload.get("iss"),
        "audience": payload.get("aud"),
    }


def verify_jwt_from_headers(
    headers: dict[str, str],
    secret: str,
    *,
    issuer: str | None = None,
    audience: str | None = None,
    leeway_seconds: int = 30,
) -> dict[str, Any]:
    token = _extract_bearer_token(_lower_headers(headers))
    return verify_jwt_hs256(
        token,
        secret,
        issuer=issuer,
        audience=audience,
        leeway_seconds=leeway_seconds,
    )
