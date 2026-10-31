"""Machine-checkable rules from POLICY.md.

Every tool resolves paths and filters payloads through this module. Tools never
touch the filesystem directly, so a policy change here applies everywhere.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PolicyError(PermissionError):
    """Raised when a request falls outside the allowed surface."""


READ_ALLOWLIST: tuple[str, ...] = (
    "README.md",
    "AGENTS.md",
    "docs/*.md",
    "docs/**/*.md",
    "docs/reports.json",
    "config/*.json",
    "artifacts/*/report.json",
    "artifacts/*/metrics.csv",
)

_TEST_KEY = re.compile(r"^(test|test_.*|reserved_test.*|final_test.*)$", re.IGNORECASE)
_FINAL_TEST_STATUS = re.compile(r"(final_test_complete|test_complete|test_reported)", re.IGNORECASE)


def _matches(rel: str) -> bool:
    return any(fnmatch.fnmatchcase(rel, pattern) for pattern in READ_ALLOWLIST)


@dataclass(frozen=True)
class RepoPolicy:
    root: Path
    allow_test_role: bool = False

    def resolve_read(self, relative: str) -> Path:
        """Return an absolute path if reading it is allowed, else raise."""
        if not relative or relative.startswith(("/", "~")):
            raise PolicyError(f"Only repository-relative paths are allowed: {relative!r}")
        candidate = (self.root / relative).resolve()
        try:
            rel = candidate.relative_to(self.root.resolve()).as_posix()
        except ValueError as exc:
            raise PolicyError(f"Path escapes the target repository: {relative!r}") from exc
        if not _matches(rel):
            raise PolicyError(f"Reading {rel!r} is not permitted by POLICY.md.")
        if not candidate.is_file():
            raise FileNotFoundError(rel)
        return candidate

    def read_text(self, relative: str) -> str:
        return self.resolve_read(relative).read_text(encoding="utf-8")

    def iter_allowed(self, pattern: str) -> list[str]:
        """List repository-relative files matching an allowlisted pattern."""
        if pattern not in READ_ALLOWLIST:
            raise PolicyError(f"Pattern {pattern!r} is not in the read allowlist.")
        root = self.root.resolve()
        out: list[str] = []
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                try:
                    out.append(path.resolve().relative_to(root).as_posix())
                except ValueError:
                    continue
        return out

    def redact_reserved_test(self, payload: Any, protocol_status: str | None = None) -> Any:
        """Remove test-role sections from artifact payloads unless permitted."""
        if self.allow_test_role:
            return payload
        if protocol_status and _FINAL_TEST_STATUS.search(protocol_status):
            return payload
        return _redact(payload)

    def check_metric_path(self, dotted: str) -> None:
        if self.allow_test_role:
            return
        for part in dotted.split("."):
            if _TEST_KEY.match(part):
                raise PolicyError(
                    f"Metric path {dotted!r} addresses a reserved test role; denied by POLICY.md."
                )

    def is_reserved_test_label(self, value: str | None, protocol_status: str | None = None) -> bool:
        """True when a role/split label is a reserved test section that must stay hidden."""
        if self.allow_test_role:
            return False
        if protocol_status and _FINAL_TEST_STATUS.search(protocol_status):
            return False
        return isinstance(value, str) and bool(_TEST_KEY.match(value))


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(key, str) and _TEST_KEY.match(key):
                out[key] = "[redacted: reserved test role]"
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
