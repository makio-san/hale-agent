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
    "artifacts/*/preflight.json",
)

_TEST_KEY = re.compile(r"^(test|test_.*|reserved_test.*|final_test.*)$", re.IGNORECASE)
_TEST_KEY_EXCEPTIONS = {
    "final_test_allowed",
    "final_test_complete",
    "test_complete",
    "test_reported",
}
_FINAL_TEST_STATUS = re.compile(r"(final_test_complete|test_complete|test_reported)", re.IGNORECASE)
_SCRIPT_NAME = re.compile(r"^[a-z0-9_]+$")
_ARTIFACT_DIR = re.compile(r"^artifacts/[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def _matches(rel: str) -> bool:
    return any(fnmatch.fnmatchcase(rel, pattern) for pattern in READ_ALLOWLIST)


@dataclass(frozen=True)
class RepoPolicy:
    root: Path
    allow_test_role: bool = False
    python: Path | None = None

    def interpreter(self) -> Path:
        path = self.python or (self.root / ".venv" / "bin" / "python")
        if not path.is_file():
            raise PolicyError(
                f"Python interpreter not found at {path}. Set HALE_PYTHON to the Helio24 venv."
            )
        return path

    def _relative(self, relative: str) -> tuple[str, Path]:
        if not relative or relative.startswith(("/", "~")):
            raise PolicyError(f"Only repository-relative paths are allowed: {relative!r}")
        candidate = (self.root / relative).resolve()
        try:
            rel = candidate.relative_to(self.root.resolve()).as_posix()
        except ValueError as exc:
            raise PolicyError(f"Path escapes the target repository: {relative!r}") from exc
        return rel, candidate

    def resolve_read(self, relative: str) -> Path:
        """Return an absolute path if reading it is allowed, else raise."""
        rel, candidate = self._relative(relative)
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
            if _is_reserved_test_key(part):
                raise PolicyError(
                    f"Metric path {dotted!r} addresses a reserved test role; denied by POLICY.md."
                )

    def is_reserved_test_label(self, value: str | None, protocol_status: str | None = None) -> bool:
        """True when a role/split label is a reserved test section that must stay hidden."""
        if self.allow_test_role:
            return False
        if protocol_status and _FINAL_TEST_STATUS.search(protocol_status):
            return False
        return isinstance(value, str) and _is_reserved_test_key(value)

    def resolve_script(self, name: str, allowed: set[str]) -> Path:
        if not _SCRIPT_NAME.match(name) or name not in allowed:
            raise PolicyError(f"Script {name!r} is not in the Stage 2 allowlist.")
        rel, candidate = self._relative(f"scripts/{name}.py")
        if rel != f"scripts/{name}.py":
            raise PolicyError(f"Script path escaped the scripts directory: {name!r}")
        if not candidate.is_file():
            raise FileNotFoundError(rel)
        return candidate

    def resolve_new_artifact_dir(self, relative: str) -> Path:
        rel, candidate = self._relative(relative)
        if not _ARTIFACT_DIR.match(rel):
            raise PolicyError(
                f"Output must be a new directory of the form artifacts/<name>, not {rel!r}."
            )
        if candidate.exists():
            raise PolicyError(f"Output {rel!r} already exists; choose a new directory.")
        return candidate

    def resolve_existing_artifact_dir(self, relative: str) -> Path:
        rel, candidate = self._relative(relative)
        if not _ARTIFACT_DIR.match(rel):
            raise PolicyError(f"Artifact directory must match artifacts/<name>, not {rel!r}.")
        if not candidate.is_dir():
            raise FileNotFoundError(rel)
        return candidate

    def assert_development_execution(self, protocol: dict[str, Any]) -> None:
        """Refuse a script run that would open reserved test rows."""
        if self.allow_test_role:
            return
        data = protocol.get("development_data")
        if isinstance(data, dict) and data.get("reserved_test_rows") is True:
            raise PolicyError("This protocol marks reserved_test_rows; execution is denied.")
        if self.is_reserved_test_label(str(protocol.get("status") or "")):
            raise PolicyError("Protocol status addresses a reserved test role; execution is denied.")


def _is_reserved_test_key(value: str) -> bool:
    if value.lower() in _TEST_KEY_EXCEPTIONS:
        return False
    return bool(_TEST_KEY.match(value))


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(key, str) and _is_reserved_test_key(key):
                out[key] = "[redacted: reserved test role]"
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
