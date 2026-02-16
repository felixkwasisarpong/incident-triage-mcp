from __future__ import annotations
import os
import time
import hashlib
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

def _required_confirmation_token() -> str:
    # You set this in deployment/Claude env.
    tok = os.getenv("CONFIRM_TOKEN")
    if not tok:
        raise SafeActionError("CONFIRM_TOKEN is not set on the server. Refusing non-dry-run safe action.")
    return tok

def enforce(ctx: SafeActionContext) -> None:
    """
    Enforces:
    - dry_run default behavior is safe
    - if not dry_run: must provide reason + correct confirm_token
    """
    if ctx.dry_run:
        return

    if not ctx.reason or len(ctx.reason.strip()) < 8:
        raise SafeActionError("Non-dry-run requires a 'reason' (>= 8 chars).")

    required = _required_confirmation_token()
    if not ctx.confirm_token or ctx.confirm_token.strip() != required:
        raise SafeActionError("Invalid or missing confirm_token for non-dry-run action.")