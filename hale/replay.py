"""Stage 4: replay archived Helio24 decisions against Hale's encoded rules.

The catalog is the benchmark. Each case materializes a compact snapshot of the
repository as it stood at a decision, runs one allowlisted tool, and scores the
outcome against the human record. This does not call a model and does not write
into a live Helio24 checkout.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from hale.policy import RepoPolicy
from hale.tools import default_registry

Kind = Literal["interpret", "propose", "read", "run", "inventory"]
Status = Literal["passed", "failed", "skipped"]

_DEFAULT_CATALOG = Path(__file__).with_name("cases") / "helio24_replay.json"

_CHECK_SCRIPT = (
    "import argparse, json\n"
    "from pathlib import Path\n"
    "parser = argparse.ArgumentParser()\n"
    "parser.add_argument('--config', type=Path, required=True)\n"
    "parser.add_argument('--output', type=Path, required=True)\n"
    "args = parser.parse_args()\n"
    "protocol = json.loads(args.config.read_text())\n"
    "args.output.mkdir(parents=True, exist_ok=False)\n"
    "(args.output / 'preflight.json').write_text(json.dumps({\n"
    "    'protocol_id': protocol.get('id'),\n"
    "    'ready_for_training': False,\n"
    "}) + '\\n')\n"
)

_RUN_STUB = "raise SystemExit('replay stub should not fit a model')\n"


class SourceLock(BaseModel):
    path: str
    pointer: str = Field(description="Dotted JSON path, or 'contains' for Markdown.")
    equals: Any


class ReplayAction(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class ReplayExpect(BaseModel):
    decision: str | None = None
    observed: Any = None
    value: Any = None
    version: int | None = None
    status: str | None = None
    frozen: dict[str, Any] = Field(default_factory=dict)
    reserved_test_rows: bool | None = None
    policy_error: str | None = None
    forbidden_values: list[Any] = Field(default_factory=list)
    present_tools: list[str] = Field(default_factory=list)
    absent_tools: list[str] = Field(default_factory=list)


class ReplayCase(BaseModel):
    id: str
    kind: Kind
    title: str
    gold_source: str
    claims: list[str] = Field(default_factory=list)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    action: ReplayAction
    expect: ReplayExpect = Field(default_factory=ReplayExpect)
    source_locks: list[SourceLock] = Field(default_factory=list)


class ReplayCatalog(BaseModel):
    name: str
    version: int
    cases: list[ReplayCase]


@dataclass
class CaseResult:
    id: str
    kind: str
    title: str
    gold_source: str
    status: Status
    checks: dict[str, Status]
    details: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "gold_source": self.gold_source,
            "status": self.status,
            "checks": self.checks,
            "details": self.details,
        }


@dataclass
class ReplayReport:
    catalog: str
    cases: list[CaseResult]

    @property
    def summary(self) -> dict[str, Any]:
        counts = {"passed": 0, "failed": 0, "skipped": 0}
        claims: dict[str, dict[str, int]] = {}
        for row in self.cases:
            counts[row.status] += 1
            for claim, status in row.checks.items():
                bucket = claims.setdefault(claim, {"passed": 0, "failed": 0, "skipped": 0})
                bucket[status] += 1
        return {"total": len(self.cases), **counts, "claims": claims}

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": 4,
            "catalog": self.catalog,
            "summary": self.summary,
            "cases": [row.as_dict() for row in self.cases],
        }


def default_catalog_path() -> Path:
    return _DEFAULT_CATALOG


def load_catalog(path: Path | None = None) -> ReplayCatalog:
    target = path or default_catalog_path()
    return ReplayCatalog.model_validate(json.loads(target.read_text(encoding="utf-8")))


def run_catalog(
    catalog: ReplayCatalog | None = None,
    *,
    lock_repo: Path | None = None,
    only: list[str] | None = None,
    catalog_path: Path | None = None,
) -> ReplayReport:
    loaded = catalog or load_catalog(catalog_path)
    selected = [case for case in loaded.cases if not only or case.id in only]
    if only:
        missing = sorted(set(only) - {case.id for case in selected})
        if missing:
            raise ValueError(f"Unknown replay case: {', '.join(missing)}")
    results = [run_case(case, lock_repo=lock_repo) for case in selected]
    return ReplayReport(catalog=loaded.name, cases=results)


def run_case(case: ReplayCase, *, lock_repo: Path | None = None) -> CaseResult:
    checks: dict[str, Status] = {}
    details: list[str] = []
    for lock in case.source_locks:
        status, note = _verify_lock(lock, lock_repo)
        checks[f"source_lock:{lock.path}"] = status
        if note:
            details.append(note)

    if case.kind == "inventory":
        _score_inventory(case, checks, details)
    else:
        with tempfile.TemporaryDirectory(prefix="hale-replay-") as tmp:
            root = Path(tmp)
            _materialize(root, case)
            policy = RepoPolicy(root)
            outcome = default_registry().call(policy, case.action.tool, dict(case.action.args))
            _score_outcome(case, policy, outcome, checks, details)

    claimed = {name: checks[name] for name in case.claims if name in checks}
    claimed.update((name, status) for name, status in checks.items() if name.startswith("source_lock:"))
    # Keep untagged operational checks too.
    for name, status in checks.items():
        claimed.setdefault(name, status)

    if any(status == "failed" for status in claimed.values()):
        status: Status = "failed"
    elif claimed and all(status == "skipped" for status in claimed.values()):
        status = "skipped"
    else:
        status = "passed"
    return CaseResult(case.id, case.kind, case.title, case.gold_source, status, claimed, details)


def _materialize(root: Path, case: ReplayCase) -> None:
    files = dict(case.snapshot)
    if case.kind == "run":
        files.setdefault("scripts/check_evaluation_protocol.py", _CHECK_SCRIPT)
        files.setdefault("scripts/run_walk_forward.py", _RUN_STUB)
        files.setdefault("README.md", "# Replay\n")
    for rel, content in files.items():
        path = root / rel
        if ".." in Path(rel).parts or Path(rel).is_absolute():
            raise ValueError(f"Replay snapshot path is not repository-relative: {rel}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, (dict, list)):
            path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        else:
            path.write_text(str(content), encoding="utf-8")


def _score_outcome(
    case: ReplayCase,
    policy: RepoPolicy,
    outcome: dict[str, Any],
    checks: dict[str, Status],
    details: list[str],
) -> None:
    expect = case.expect
    if expect.policy_error:
        ok = (not outcome.get("ok")) and expect.policy_error in str(outcome.get("details") or "")
        _record(checks, details, "policy_denied", ok, outcome.get("details") or outcome.get("error"))
        return

    if not outcome.get("ok"):
        _record(checks, details, "tool_ok", False, outcome.get("details") or outcome.get("error"))
        return
    _record(checks, details, "tool_ok", True)

    result = outcome.get("result") if isinstance(outcome.get("result"), dict) else {}
    dumped = json.dumps(result, ensure_ascii=False, default=str)

    if expect.decision is not None:
        _record(checks, details, "accept_reject_match", result.get("decision") == expect.decision, result.get("decision"))
    if expect.observed is not None:
        _record(checks, details, "numeric_match", _same(result.get("observed"), expect.observed), result.get("observed"))
    if expect.value is not None:
        _record(checks, details, "numeric_match", _same(result.get("value"), expect.value), result.get("value"))
    if expect.version is not None:
        _record(checks, details, "propose_version", result.get("version") == expect.version, result.get("version"))
    if expect.status is not None:
        _record(checks, details, "propose_status", result.get("status") == expect.status, result.get("status"))

    if expect.frozen or expect.reserved_test_rows is not None:
        written = _proposed_protocol(policy, result)
        for key, gold in expect.frozen.items():
            _record(checks, details, f"frozen:{key}", _same(written.get(key), gold), written.get(key))
        if expect.reserved_test_rows is not None:
            data = written.get("development_data")
            observed = data.get("reserved_test_rows") if isinstance(data, dict) else None
            _record(checks, details, "reserved_test_closed", observed is expect.reserved_test_rows, observed)

    for forbidden in expect.forbidden_values:
        _record(
            checks,
            details,
            "no_test_leak",
            not _contains(result, forbidden) and str(forbidden) not in dumped,
            forbidden,
        )


def _score_inventory(case: ReplayCase, checks: dict[str, Status], details: list[str]) -> None:
    names = set(default_registry().names())
    for tool in case.expect.present_tools:
        _record(checks, details, f"present:{tool}", tool in names, tool)
    for tool in case.expect.absent_tools:
        _record(checks, details, f"absent:{tool}", tool not in names, tool)


def _proposed_protocol(policy: RepoPolicy, result: dict[str, Any]) -> dict[str, Any]:
    path = result.get("path")
    if not isinstance(path, str):
        return {}
    try:
        payload = json.loads(policy.read_text(path))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _verify_lock(lock: SourceLock, lock_repo: Path | None) -> tuple[Status, str]:
    if lock_repo is None:
        return "skipped", f"{lock.path}: lock repo not provided"
    path = lock_repo / lock.path
    if not path.is_file():
        if lock.path.startswith("artifacts/"):
            return "skipped", f"{lock.path}: missing from lock repo"
        return "failed", f"{lock.path}: missing from lock repo"
    text = path.read_text(encoding="utf-8")
    if lock.pointer == "contains":
        ok = str(lock.equals) in text
        return ("passed" if ok else "failed", "" if ok else f"{lock.path} does not contain {lock.equals!r}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return "failed", f"{lock.path}: not JSON"
    observed = _lookup(payload, lock.pointer)
    if _same(observed, lock.equals):
        return "passed", ""
    return "failed", f"{lock.path}:{lock.pointer} is {observed!r}, expected {lock.equals!r}"


def _lookup(payload: Any, dotted: str) -> Any:
    node = payload
    for part in dotted.split("."):
        if isinstance(node, list) and part.isdigit():
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _contains(payload: Any, needle: Any) -> bool:
    if _same(payload, needle):
        return True
    if isinstance(payload, dict):
        return any(_contains(item, needle) for item in payload.values())
    if isinstance(payload, list):
        return any(_contains(item, needle) for item in payload)
    return False


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return (left is True and right is True) or (left is False and right is False)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    return left == right


def _record(checks: dict[str, Status], details: list[str], name: str, ok: bool, detail: Any = None) -> None:
    checks[name] = "passed" if ok else "failed"
    if not ok and detail is not None:
        details.append(f"{name}: {detail}")
