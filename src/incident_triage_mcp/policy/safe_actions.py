from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

class SafeActionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SafeActionContext:
    tool_name: str
    role: str
    dry_run: bool
    reason: str | None
    confirm_token: str | None
    idempotency_key: str | None


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _configured_approval_tokens() -> tuple[list[str], list[str]]:
    clear_tokens = _split_csv(os.getenv("CONFIRM_TOKENS"))
    legacy_token = (os.getenv("CONFIRM_TOKEN") or "").strip()
    if legacy_token and legacy_token not in clear_tokens:
        clear_tokens.append(legacy_token)

    hashed_tokens = _split_csv(os.getenv("CONFIRM_TOKENS_SHA256"))
    legacy_hash = (os.getenv("CONFIRM_TOKEN_SHA256") or "").strip().lower()
    if legacy_hash and legacy_hash not in hashed_tokens:
        hashed_tokens.append(legacy_hash)

    return clear_tokens, hashed_tokens


def _validate_confirm_token(confirm_token: str | None) -> None:
    clear_tokens, hashed_tokens = _configured_approval_tokens()
    if not clear_tokens and not hashed_tokens:
        raise SafeActionError(
            "No approval token configured. Set CONFIRM_TOKEN/CONFIRM_TOKENS or CONFIRM_TOKEN_SHA256/CONFIRM_TOKENS_SHA256."
        )

    provided = (confirm_token or "").strip()
    if not provided:
        raise SafeActionError("Invalid or missing confirm_token for non-dry-run action.")

    for candidate in clear_tokens:
        if hmac.compare_digest(provided, candidate):
            return

    provided_hash = _token_sha256(provided)
    for candidate_hash in hashed_tokens:
        if hmac.compare_digest(provided_hash, candidate_hash.lower()):
            return

    raise SafeActionError("Invalid or missing confirm_token for non-dry-run action.")


def _validate_tool_preconditions(ctx: SafeActionContext) -> None:
    if ctx.tool_name == "jira.create_ticket":
        key = (ctx.idempotency_key or "").strip()
        if not key:
            raise SafeActionError("Non-dry-run jira.create_ticket requires idempotency_key.")
        if len(key) < 8:
            raise SafeActionError("Non-dry-run jira.create_ticket requires idempotency_key with at least 8 characters.")

def enforce(ctx: SafeActionContext) -> None:
    """
    Enforces:
    - dry_run default behavior is safe
    - if not dry_run: must provide reason + valid approval token
    - tool-specific preconditions
    """
    if ctx.dry_run:
        return

    if not ctx.reason or len(ctx.reason.strip()) < 8:
        raise SafeActionError("Non-dry-run requires a 'reason' (>= 8 chars).")

    _validate_confirm_token(ctx.confirm_token)
    _validate_tool_preconditions(ctx)
