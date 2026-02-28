#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


FORBIDDEN_FILENAME_TOKENS = ("key", "token", "secret", ".env")
SECRET_LINE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key-like pattern (AKIA...)"),
    (re.compile(r"xoxb-[0-9A-Za-z-]+"), "Slack bot token-like pattern (xoxb-)"),
    (
        re.compile(r"-----BEGIN [A-Z ]+-----"),
        "Private key or certificate block header",
    ),
)


def _error(msg: str, errors: list[str]) -> None:
    errors.append(msg)


def validate_contrib(root: Path) -> int:
    errors: list[str] = []
    contrib = root / "contrib"

    if not contrib.exists() or not contrib.is_dir():
        _error("Missing required directory: contrib/", errors)
        return _finish(errors)

    root_readme = contrib / "README.md"
    if not root_readme.is_file():
        _error("Missing required file: contrib/README.md", errors)

    subdirs = sorted([p for p in contrib.iterdir() if p.is_dir() and not p.name.startswith(".")])
    for subdir in subdirs:
        readme = subdir / "README.md"
        if not readme.is_file():
            rel = readme.relative_to(root)
            _error(f"Missing required file: {rel}", errors)

    for path in sorted(p for p in contrib.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        lower_name = path.name.lower()
        if any(token in lower_name for token in FORBIDDEN_FILENAME_TOKENS):
            _error(
                f"Forbidden filename under contrib/: {rel} "
                "(contains key/token/secret/.env marker)",
                errors,
            )

        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for pattern, reason in SECRET_LINE_PATTERNS:
                if pattern.search(line):
                    _error(f"Secret-like content in {rel}:{line_no} ({reason})", errors)

    return _finish(errors)


def _finish(errors: list[str]) -> int:
    if not errors:
        print("contrib validation passed")
        return 0

    print("contrib validation failed:")
    for err in errors:
        print(f"- {err}")
    print("Fix the issues above. Keep secrets and credentials out of contrib/.")
    return 1


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    return validate_contrib(root)


if __name__ == "__main__":
    raise SystemExit(main())
