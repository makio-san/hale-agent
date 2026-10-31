"""Stage 3 tools: propose, interpret, draft, register and open a review PR."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from operator import eq, ge, gt, le, lt
from typing import Any

from pydantic import BaseModel, Field

from hale.gitops import GitOps
from hale.policy import PolicyError, RepoPolicy
from hale.tools import Tool

_OPS = {">=": ge, ">": gt, "<=": le, "<": lt, "==": eq}
_FROZEN_FIELDS = {
    "id",
    "version",
    "status",
    "supersedes",
    "roles",
    "development_data",
    "label_inventory",
    "measurement_contract",
    "data_contract",
    "source_manifest",
    "question",
    "observation_hours",
    "prediction_hours",
    "time_scale",
    "development_selection",
    "gates",
    "gate_details",
    "evidence_files",
    "label_policy",
}
_BRANCH = re.compile(r"^hale/[a-z0-9][a-z0-9._/-]{0,80}$")
_COMMIT = re.compile(r"^[a-z]+(?:\([a-z0-9-]+\))?: .+[.]$")
_TABLE = re.compile(r"(?:^\|.*\n)+", re.M)


class ProposeProtocolArgs(BaseModel):
    base: str = Field(description="Existing protocol path, e.g. config/experiment5-v8.json")
    hypothesis: str = Field(min_length=8, description="What this revision will test, written before any run.")
    acceptance_description: str = Field(min_length=8, description="Human readable acceptance rule.")
    metric_path: str = Field(description="Dotted path in a later report.json, e.g. metrics.validation.recall")
    op: str = Field(description="One of >=, >, <=, <, ==")
    value: float = Field(description="Threshold compared against metric_path.")
    revision_reason: str = Field(min_length=8, description="Why a new protocol version is required.")
    changes: dict[str, Any] | None = Field(
        default=None,
        description="Optional overlay. Frozen data-contract fields are rejected.",
    )


class InterpretResultArgs(BaseModel):
    protocol: str = Field(description="Protocol that froze the acceptance rule.")
    artifact: str = Field(description="Artifact directory that contains report.json.")


class DraftReportArgs(BaseModel):
    report_id: str = Field(description="New slug, e.g. calibration-windows-20261030")
    en_markdown: str = Field(min_length=20, description="English edition. Tables must match the Turkish numbers.")
    tr_markdown: str = Field(min_length=20, description="Turkish edition. Tables must match the English numbers.")


class RegisterReportArgs(BaseModel):
    report_id: str = Field(description="Slug previously written by draft_report.")


class OpenPullRequestArgs(BaseModel):
    branch: str = Field(description="New branch name starting with hale/, e.g. hale/experiment5-v9")
    title: str = Field(min_length=8)
    body: str = Field(min_length=8)
    message: str = Field(description="Conventional commit ending with a period.")
    files: list[str] = Field(min_length=1, description="Repository-relative files already approved for pull_request.")
    confirm: bool = False


def propose_protocol(policy: RepoPolicy, args: ProposeProtocolArgs) -> dict[str, Any]:
    if args.op not in _OPS:
        raise PolicyError("op must be one of >=, >, <=, <, ==.")
    policy.check_metric_path(args.metric_path)
    base = json.loads(policy.read_text(args.base))
    if not isinstance(base, dict) or not isinstance(base.get("id"), str):
        raise PolicyError("Base protocol must be a JSON object with an id.")
    if not isinstance(base.get("version"), int) or base["version"] < 1:
        raise PolicyError("Base protocol must have a positive integer version.")
    if args.changes:
        frozen = sorted(key for key in args.changes if key in _FROZEN_FIELDS)
        if frozen:
            raise PolicyError(f"Cannot change frozen fields: {', '.join(frozen)}.")
        base.update(args.changes)
    version = base["version"] + 1
    path = f"config/{base['id']}-v{version}.json"
    protocol = dict(base)
    protocol.update(
        {
            "version": version,
            "status": "design_proposed",
            "supersedes": args.base,
            "revision_reason": args.revision_reason,
            "hypothesis": args.hypothesis,
            "acceptance_rule": {
                "description": args.acceptance_description,
                "metric_path": args.metric_path,
                "op": args.op,
                "value": args.value,
            },
        }
    )
    data = protocol.get("development_data")
    if isinstance(data, dict):
        data = dict(data)
        data["reserved_test_rows"] = False
        protocol["development_data"] = data
    text = json.dumps(protocol, indent=2, ensure_ascii=False) + "\n"
    policy.write_new_file(path, text)
    return {
        "path": path,
        "id": protocol["id"],
        "version": version,
        "status": protocol["status"],
        "supersedes": args.base,
        "acceptance_rule": protocol["acceptance_rule"],
        "approved": False,
        "note": f"Human gate: hale approve --gate protocol {path}",
    }


def interpret_result(policy: RepoPolicy, args: InterpretResultArgs) -> dict[str, Any]:
    protocol = json.loads(policy.read_text(args.protocol))
    rule = protocol.get("acceptance_rule")
    if not isinstance(rule, dict):
        raise PolicyError("This protocol has no frozen acceptance_rule.")
    metric_path = rule.get("metric_path")
    op = rule.get("op")
    expected = rule.get("value")
    if not isinstance(metric_path, str) or op not in _OPS or not isinstance(expected, (int, float)):
        raise PolicyError("acceptance_rule must have metric_path, op and numeric value.")
    policy.check_metric_path(metric_path)
    report = json.loads(policy.read_text(f"{args.artifact}/report.json"))
    status = report.get("status")
    if isinstance(report.get("protocol"), dict):
        status = report["protocol"].get("status") or status
    report = policy.redact_reserved_test(report, protocol_status=status if isinstance(status, str) else None)
    observed = _lookup(report, metric_path)
    if isinstance(observed, str) and observed.startswith("[redacted"):
        raise PolicyError(f"{metric_path} is a reserved test result; interpretation is denied.")
    if not isinstance(observed, (int, float)):
        return {
            "decision": "undecided",
            "reason": f"{metric_path} is missing or not numeric in {args.artifact}/report.json",
            "rule": rule,
        }
    passed = bool(_OPS[op](observed, expected))
    return {
        "decision": "accept" if passed else "reject",
        "observed": observed,
        "rule": rule,
        "protocol": args.protocol,
        "artifact": args.artifact,
        "note": "Interpret only against this frozen rule. Other metrics cannot override a rejection.",
    }


def draft_report(policy: RepoPolicy, args: DraftReportArgs) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9-]+", args.report_id):
        raise PolicyError("report_id must be a lowercase slug.")
    if "{{TABLE_" in args.en_markdown or "{{TABLE_" in args.tr_markdown:
        raise PolicyError("Unresolved translation placeholders are not allowed.")
    _assert_numeric_parity(args.en_markdown, args.tr_markdown)
    en_path = f"docs/{args.report_id}.md"
    tr_path = f"docs/{args.report_id}.tr.md"
    policy.write_new_file(en_path, args.en_markdown if args.en_markdown.endswith("\n") else args.en_markdown + "\n")
    policy.write_new_file(tr_path, args.tr_markdown if args.tr_markdown.endswith("\n") else args.tr_markdown + "\n")
    return {"id": args.report_id, "en": en_path, "tr": tr_path, "registered": False}


def register_report(policy: RepoPolicy, args: RegisterReportArgs) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9-]+", args.report_id):
        raise PolicyError("report_id must be a lowercase slug.")
    en = f"docs/{args.report_id}.md"
    tr = f"docs/{args.report_id}.tr.md"
    en_text = policy.read_text(en)
    tr_text = policy.read_text(tr)
    _assert_numeric_parity(en_text, tr_text)
    entry = {
        "id": args.report_id,
        "source_language": "en",
        "source_sha256": sha256(policy.resolve_read(en).read_bytes()).hexdigest(),
        "en": f"{args.report_id}.md",
        "tr": f"{args.report_id}.tr.md",
    }
    policy.append_report_index(entry)
    return entry


def open_pull_request(policy: RepoPolicy, args: OpenPullRequestArgs) -> dict[str, Any]:
    if not args.confirm:
        raise PolicyError("open_pull_request needs confirm=true after an explicit user request.")
    if not _BRANCH.match(args.branch):
        raise PolicyError("branch must start with hale/ and use lowercase slug characters.")
    if not _COMMIT.match(args.message):
        raise PolicyError("Commit message must be type(scope): summary. ending with a period.")
    policy.assert_git_allowed()
    policy.require_pull_request_approval(args.files)
    return GitOps(policy.root).open_pull_request(
        branch=args.branch,
        title=args.title,
        body=args.body,
        files=args.files,
        message=args.message,
    )


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


def _assert_numeric_parity(en: str, tr: str) -> None:
    left, right = _TABLE.findall(en), _TABLE.findall(tr)
    if len(left) != len(right):
        raise PolicyError("English and Turkish editions must contain the same number of tables.")
    if any(_numeric_cells(a) != _numeric_cells(b) for a, b in zip(left, right)):
        raise PolicyError("Numeric table cells differ between English and Turkish editions.")


def _numeric_cells(table: str) -> list[list[list[str]]]:
    return [
        [sorted(re.findall(r"[-+]?\d+(?:[.,]\d+)*(?:e[+-]?\d+)?", cell)) for cell in row.split("|")[1:-1]]
        for row in table.splitlines()[2:]
    ]


TOOLS: list[Tool] = [
    Tool(
        name="propose_protocol",
        description=(
            "Write a new config/<id>-vN.json that supersedes an existing protocol. "
            "Freezes hypothesis and acceptance_rule. Does not approve execution. "
            "A human must run: hale approve --gate protocol <path>"
        ),
        args=ProposeProtocolArgs,
        handler=propose_protocol,
    ),
    Tool(
        name="interpret_result",
        description=(
            "Compare an artifact report.json against the protocol's frozen acceptance_rule. "
            "Returns accept or reject. Other metrics cannot override a rejection."
        ),
        args=InterpretResultArgs,
        handler=interpret_result,
    ),
    Tool(
        name="draft_report",
        description=(
            "Write a new bilingual report pair under docs/. Files must not already exist. "
            "Numeric table cells must be identical in both languages."
        ),
        args=DraftReportArgs,
        handler=draft_report,
    ),
    Tool(
        name="register_report",
        description="Append a new row to docs/reports.json without changing existing entries.",
        args=RegisterReportArgs,
        handler=register_report,
    ),
    Tool(
        name="open_pull_request",
        description=(
            "Create a branch, commit approved files, push, and open a GitHub pull request. "
            "Requires HALE_ALLOW_GIT=1, confirm=true, and hale approve --gate pull_request. "
            "Does not merge."
        ),
        args=OpenPullRequestArgs,
        handler=open_pull_request,
    ),
]
