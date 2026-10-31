"""Stage 1 tools: read-only inspection of protocols, reports and artifacts."""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from pydantic import BaseModel, Field

from hale.policy import RepoPolicy
from hale.tools import Tool


# --------------------------------------------------------------------------- #
# list_experiments
# --------------------------------------------------------------------------- #


class ListExperimentsArgs(BaseModel):
    """No arguments."""


def _load_protocols(policy: RepoPolicy) -> list[dict[str, Any]]:
    protocols = []
    for rel in policy.iter_allowed("config/*.json"):
        try:
            data = json.loads(policy.read_text(rel))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or "id" not in data:
            continue
        protocols.append(
            {
                "path": rel,
                "id": data.get("id"),
                "version": data.get("version"),
                "status": data.get("status"),
                "supersedes": data.get("supersedes"),
                "revision_reason": data.get("revision_reason"),
            }
        )
    return protocols


def list_experiments(policy: RepoPolicy, _: ListExperimentsArgs) -> dict[str, Any]:
    protocols = _load_protocols(policy)
    by_id: dict[str, list[dict[str, Any]]] = {}
    for item in protocols:
        by_id.setdefault(str(item["id"]), []).append(item)
    experiments = []
    for exp_id, versions in sorted(by_id.items()):
        versions.sort(key=lambda v: (v["version"] is None, v["version"] or 0, v["path"]))
        latest = versions[-1]
        experiments.append(
            {
                "id": exp_id,
                "latest_path": latest["path"],
                "latest_version": latest["version"],
                "status": latest["status"],
                "versions": [v["path"] for v in versions],
            }
        )
    return {"count": len(experiments), "experiments": experiments}


# --------------------------------------------------------------------------- #
# get_experiment
# --------------------------------------------------------------------------- #


class GetExperimentArgs(BaseModel):
    path: str = Field(description="Repository-relative protocol path, e.g. config/experiment5-v8.json")


def get_experiment(policy: RepoPolicy, args: GetExperimentArgs) -> dict[str, Any]:
    data = json.loads(policy.read_text(args.path))
    reports = _load_report_index(policy)
    related = [r for r in reports if _mentions(r, data)]
    return {"path": args.path, "protocol": data, "related_reports": related}


def _mentions(report: dict[str, Any], protocol: dict[str, Any]) -> bool:
    exp_id = str(protocol.get("id", "")).lower()
    rid = str(report.get("id", "")).lower()
    return bool(exp_id) and (exp_id in rid or rid in exp_id)


# --------------------------------------------------------------------------- #
# search_reports
# --------------------------------------------------------------------------- #


class SearchReportsArgs(BaseModel):
    query: str = Field(min_length=2, description="Case-insensitive substring or regular expression.")
    max_hits: int = Field(default=20, ge=1, le=100)
    regex: bool = False


def _load_report_index(policy: RepoPolicy) -> list[dict[str, Any]]:
    try:
        return json.loads(policy.read_text("docs/reports.json"))
    except FileNotFoundError:
        return []


def search_reports(policy: RepoPolicy, args: SearchReportsArgs) -> dict[str, Any]:
    pattern = re.compile(args.query if args.regex else re.escape(args.query), re.IGNORECASE)
    hits: list[dict[str, Any]] = []
    files = policy.iter_allowed("docs/*.md") + policy.iter_allowed("docs/**/*.md")
    for rel in dict.fromkeys(files):
        for number, line in enumerate(policy.read_text(rel).splitlines(), start=1):
            if pattern.search(line):
                hits.append({"path": rel, "line": number, "text": line.strip()[:300]})
                if len(hits) >= args.max_hits:
                    return {"truncated": True, "hits": hits}
    return {"truncated": False, "hits": hits}


# --------------------------------------------------------------------------- #
# read_document
# --------------------------------------------------------------------------- #


class ReadDocumentArgs(BaseModel):
    path: str = Field(description="Repository-relative Markdown or JSON path under docs/ or config/.")
    start_line: int = Field(default=1, ge=1)
    max_lines: int = Field(default=120, ge=1, le=400)


def read_document(policy: RepoPolicy, args: ReadDocumentArgs) -> dict[str, Any]:
    lines = policy.read_text(args.path).splitlines()
    begin = args.start_line - 1
    chunk = lines[begin : begin + args.max_lines]
    return {
        "path": args.path,
        "start_line": args.start_line,
        "end_line": begin + len(chunk),
        "total_lines": len(lines),
        "text": "\n".join(chunk),
    }


# --------------------------------------------------------------------------- #
# read_artifact
# --------------------------------------------------------------------------- #


class ReadArtifactArgs(BaseModel):
    artifact: str = Field(description="Artifact directory name under artifacts/, e.g. walk_forward_20261028_r1")
    path: str = Field(
        default="",
        description="Dotted key path inside report.json, e.g. protocol.status or metrics.recall. Empty lists top-level keys.",
    )
    metrics_rows: int = Field(default=0, ge=0, le=200, description="If > 0, also return this many rows of metrics.csv.")


def read_artifact(policy: RepoPolicy, args: ReadArtifactArgs) -> dict[str, Any]:
    if "/" in args.artifact or args.artifact.startswith("."):
        raise ValueError("artifact must be a bare directory name")
    policy.check_metric_path(args.path) if args.path else None
    report = json.loads(policy.read_text(f"artifacts/{args.artifact}/report.json"))
    status = _nested_status(report)
    report = policy.redact_reserved_test(report, protocol_status=status)

    node: Any = report
    if args.path:
        for part in args.path.split("."):
            if isinstance(node, list) and part.isdigit():
                node = node[int(part)]
            elif isinstance(node, dict) and part in node:
                node = node[part]
            else:
                raise KeyError(f"{args.path!r} not found in report.json")
    out: dict[str, Any] = {"artifact": args.artifact, "path": args.path or None}
    if args.path:
        out["value"] = node
    else:
        out["keys"] = sorted(node.keys()) if isinstance(node, dict) else None
        out["protocol_status"] = status

    if args.metrics_rows:
        try:
            text = policy.read_text(f"artifacts/{args.artifact}/metrics.csv")
        except FileNotFoundError:
            out["metrics"] = None
        else:
            reader = csv.DictReader(io.StringIO(text))
            rows = [row for _, row in zip(range(args.metrics_rows), reader)]
            out["metrics"] = policy.redact_reserved_test(
                {"columns": reader.fieldnames, "rows": rows}, protocol_status=status
            )
    return out


def _nested_status(report: dict[str, Any]) -> str | None:
    protocol = report.get("protocol")
    if isinstance(protocol, dict) and isinstance(protocol.get("status"), str):
        return protocol["status"]
    status = report.get("status")
    return status if isinstance(status, str) else None


# --------------------------------------------------------------------------- #
# registry entries
# --------------------------------------------------------------------------- #

TOOLS: list[Tool] = [
    Tool(
        name="list_experiments",
        description=(
            "List every versioned experiment protocol in config/, grouped by id with the latest "
            "version and status. Use this first to learn what exists."
        ),
        args=ListExperimentsArgs,
        handler=list_experiments,
    ),
    Tool(
        name="get_experiment",
        description=(
            "Return one protocol JSON in full plus the report index entries that refer to it. "
            "Use the path returned by list_experiments."
        ),
        args=GetExperimentArgs,
        handler=get_experiment,
    ),
    Tool(
        name="search_reports",
        description=(
            "Search every Markdown report under docs/ for a phrase and return path, line number "
            "and the matching line. Use it to locate evidence before reading a document."
        ),
        args=SearchReportsArgs,
        handler=search_reports,
    ),
    Tool(
        name="read_document",
        description=(
            "Read a slice of a report or protocol file by line range. Do not read whole files "
            "when a search hit already points at the relevant lines."
        ),
        args=ReadDocumentArgs,
        handler=read_document,
    ),
    Tool(
        name="read_artifact",
        description=(
            "Read frozen summary outputs of an experiment: report.json keys or one dotted path, "
            "optionally the first rows of metrics.csv. Reserved test sections are redacted by policy; "
            "do not try to work around that."
        ),
        args=ReadArtifactArgs,
        handler=read_artifact,
    ),
]
