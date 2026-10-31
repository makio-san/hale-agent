"""Machine-checkable rules from POLICY.md.

Every tool resolves paths and filters payloads through this module. Tools never
touch the filesystem directly, so a policy change here applies everywhere.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from hashlib import sha256
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
    "artifacts/hale_approvals/*.json",
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
_CONFIG_WRITE = re.compile(r"^config/[a-z0-9-]+-v[1-9][0-9]*\.json$")
_DOC_WRITE = re.compile(r"^docs/[a-z0-9-]+(?:\.tr)?\.md$")
_APPROVAL_FILE = re.compile(r"^artifacts/hale_approvals/[a-z0-9._-]+\.json$")
_REPORT_ID = re.compile(r"^[a-z0-9-]+$")


def _matches(rel: str) -> bool:
    return any(fnmatch.fnmatchcase(rel, pattern) for pattern in READ_ALLOWLIST)


@dataclass(frozen=True)
class RepoPolicy:
    root: Path
    allow_test_role: bool = False
    python: Path | None = None
    allow_git: bool = False

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

    def write_new_file(self, relative: str, content: str) -> Path:
        """Create a new allowlisted file. Existing files are immutable."""
        rel, candidate = self._relative(relative)
        if not (_CONFIG_WRITE.match(rel) or _DOC_WRITE.match(rel)):
            raise PolicyError(f"Writing {rel!r} is not permitted by POLICY.md.")
        if candidate.exists():
            raise PolicyError(f"{rel!r} already exists; Hale cannot overwrite frozen files.")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(content, encoding="utf-8")
        return candidate

    def append_report_index(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Append one reports.json row; existing rows must stay byte-for-byte equal in identity."""
        rel, path = self._relative("docs/reports.json")
        if rel != "docs/reports.json" or not path.is_file():
            raise PolicyError("docs/reports.json is missing or escaped the repository.")
        catalog = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(catalog, list):
            raise PolicyError("docs/reports.json must be a JSON array.")
        report_id = entry.get("id")
        if not isinstance(report_id, str) or not _REPORT_ID.match(report_id):
            raise PolicyError("Report id must be a lowercase slug.")
        if any(isinstance(row, dict) and row.get("id") == report_id for row in catalog):
            raise PolicyError(f"Report {report_id!r} is already registered.")
        catalog.append(entry)
        path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
        return entry

    def write_approval(self, target: str, gate: str, extra_files: list[str] | None = None) -> Path:
        """Record a human approval. Tools must not call this; the CLI does."""
        if gate not in {"protocol", "pull_request"}:
            raise PolicyError("Approval gate must be protocol or pull_request.")
        if gate == "protocol" and extra_files:
            raise PolicyError("protocol approval binds one config file.")
        files = [target, *(extra_files or [])]
        records = []
        for item in files:
            rel, path = self._relative(item)
            if not path.is_file():
                raise FileNotFoundError(rel)
            if gate == "protocol" and not fnmatch.fnmatchcase(rel, "config/*.json"):
                raise PolicyError("protocol approval is limited to config/*.json.")
            if gate == "pull_request" and not _pr_file_allowed(rel):
                raise PolicyError(f"{rel} cannot be included in a Hale pull request.")
            records.append({"path": rel, "sha256": sha256(path.read_bytes()).hexdigest()})
        key = _approval_key(gate, records[0]["path"])
        rel, candidate = self._relative(key)
        if not _APPROVAL_FILE.match(rel):
            raise PolicyError(f"Approval path {rel!r} is not permitted.")
        if candidate.exists():
            raise PolicyError(f"Approval {rel!r} already exists.")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        payload = {"gate": gate, "files": records}
        candidate.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return candidate

    def require_approval(self, target: str, gate: str) -> dict[str, Any]:
        rel, path = self._relative(target)
        key = _approval_key(gate, rel)
        try:
            record = json.loads(self.read_text(key))
        except FileNotFoundError as exc:
            raise PolicyError(
                f"{rel} is not approved for gate={gate}. Run: hale approve --gate {gate} {rel}"
            ) from exc
        files = record.get("files") if isinstance(record, dict) else None
        if not isinstance(files, list):
            raise PolicyError(f"Approval record {key} is malformed.")
        by_path = {row.get("path"): row.get("sha256") for row in files if isinstance(row, dict)}
        expected = by_path.get(rel)
        actual = sha256(path.read_bytes()).hexdigest()
        if expected != actual:
            raise PolicyError(f"{rel} changed after approval; approve it again.")
        return record

    def require_pull_request_approval(self, files: list[str]) -> None:
        if not files:
            raise PolicyError("A pull request needs at least one approved file.")
        record = self.require_approval(files[0], "pull_request")
        approved = {
            row.get("path"): row.get("sha256")
            for row in record.get("files", [])
            if isinstance(row, dict)
        }
        for item in files:
            rel, path = self._relative(item)
            if rel not in approved:
                raise PolicyError(f"{rel} is not in the pull_request approval set.")
            if sha256(path.read_bytes()).hexdigest() != approved[rel]:
                raise PolicyError(f"{rel} changed after approval; approve it again.")

    def assert_git_allowed(self) -> None:
        if not self.allow_git:
            raise PolicyError("Git operations are denied. Set HALE_ALLOW_GIT=1 after reviewing the files.")


def _pr_file_allowed(rel: str) -> bool:
    return bool(_CONFIG_WRITE.match(rel) or _DOC_WRITE.match(rel) or rel == "docs/reports.json")


def _approval_key(gate: str, target: str) -> str:
    slug = target.replace("/", "__").replace(".", "_")
    return f"artifacts/hale_approvals/{gate}-{slug}.json"


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
