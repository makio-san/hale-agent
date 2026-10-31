"""Stage 2 tools: typed wrappers around allowlisted Helio24 scripts."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from hale.policy import PolicyError, RepoPolicy
from hale.tools import Tool

Family = Literal["check", "run", "audit"]


@dataclass(frozen=True)
class ScriptSpec:
    name: str
    family: Family
    description: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    timeout_seconds: int = 120
    confirm: bool = False


# Paths passed through as --flag values. "output" is always a new artifact dir.
_DIR_FLAGS = {"source", "materialized", "incumbent", "raw"}
_CONFIG_FLAGS = {"config", "protocol"}

CATALOG: tuple[ScriptSpec, ...] = (
    ScriptSpec(
        name="check_evaluation_protocol",
        family="check",
        description=(
            "Snapshot protocol readiness without opening observation or outcome data. "
            "Writes preflight.json. Use this before any training script."
        ),
        required=("config", "output"),
        timeout_seconds=120,
    ),
    ScriptSpec(
        name="run_walk_forward",
        family="run",
        description="Annual walk-forward evaluation under a frozen protocol. Development roles only.",
        required=("protocol", "output"),
        timeout_seconds=3600,
        confirm=True,
    ),
    ScriptSpec(
        name="run_calibration_periods",
        family="run",
        description="Compare calibration duration trade-offs under a frozen protocol.",
        required=("protocol", "output"),
        timeout_seconds=3600,
        confirm=True,
    ),
    ScriptSpec(
        name="run_calibration_windows",
        family="run",
        description="Compare calibration windows under shared training.",
        required=("protocol", "output"),
        timeout_seconds=3600,
        confirm=True,
    ),
    ScriptSpec(
        name="run_hard_negative_years",
        family="run",
        description="Hard-negative training comparison across annual periods.",
        required=("protocol", "output"),
        timeout_seconds=3600,
        confirm=True,
    ),
    ScriptSpec(
        name="run_v2_development",
        family="run",
        description="Fit development candidates on a materialized V2 feature table.",
        required=("protocol", "materialized", "output"),
        timeout_seconds=7200,
        confirm=True,
    ),
    ScriptSpec(
        name="audit_false_alarms",
        family="audit",
        description="Audit false-alarm concentration from a frozen walk-forward artifact.",
        required=("source", "output"),
        timeout_seconds=600,
        confirm=True,
    ),
    ScriptSpec(
        name="audit_calibration_scores",
        family="audit",
        description="Measure calibration score drift and regional threshold influence.",
        required=("output",),
        timeout_seconds=600,
        confirm=True,
    ),
)

_BY_NAME = {spec.name: spec for spec in CATALOG}


class ListScriptsArgs(BaseModel):
    """No arguments."""


class RunScriptArgs(BaseModel):
    name: str = Field(description="Allowlisted script stem, e.g. check_evaluation_protocol.")
    output: str = Field(description="New directory under artifacts/, e.g. artifacts/hale_preflight_experiment5_v8.")
    config: str | None = Field(default=None, description="Repository-relative protocol JSON under config/.")
    protocol: str | None = Field(default=None, description="Repository-relative protocol JSON under config/.")
    source: str | None = Field(default=None, description="Existing artifact directory to read summaries from.")
    materialized: str | None = Field(default=None, description="Existing materialized feature artifact directory.")
    incumbent: str | None = Field(default=None, description="Existing incumbent artifact directory.")
    confirm: bool = Field(
        default=False,
        description="Required true for family=run and family=audit. Check scripts do not need it.",
    )


def list_scripts(policy: RepoPolicy, _: ListScriptsArgs) -> dict[str, Any]:
    return {
        "count": len(CATALOG),
        "scripts": [
            {
                "name": spec.name,
                "family": spec.family,
                "description": spec.description,
                "required": list(spec.required),
                "optional": list(spec.optional),
                "confirm": spec.confirm,
                "timeout_seconds": spec.timeout_seconds,
                "present": (policy.root / "scripts" / f"{spec.name}.py").is_file(),
            }
            for spec in CATALOG
        ],
    }


def run_script(policy: RepoPolicy, args: RunScriptArgs) -> dict[str, Any]:
    spec = _BY_NAME.get(args.name)
    if spec is None:
        raise PolicyError(f"Script {args.name!r} is not in the Stage 2 allowlist.")
    if spec.confirm and not args.confirm:
        raise PolicyError(
            f"{args.name} is family={spec.family} and needs confirm=true after an explicit user request."
        )
    provided = {
        "output": args.output,
        "config": args.config,
        "protocol": args.protocol,
        "source": args.source,
        "materialized": args.materialized,
        "incumbent": args.incumbent,
    }
    missing = [name for name in spec.required if not provided.get(name)]
    if missing:
        raise PolicyError(f"{spec.name} requires: {', '.join(missing)}.")
    extra = [
        name
        for name, value in provided.items()
        if value and name != "output" and name not in spec.required and name not in spec.optional
    ]
    if extra:
        raise PolicyError(f"{spec.name} does not accept: {', '.join(extra)}.")

    script = policy.resolve_script(spec.name, set(_BY_NAME))
    argv = [str(policy.interpreter()), str(script)]
    protocol_payload: dict[str, Any] | None = None
    for flag in (*spec.required, *spec.optional):
        value = provided.get(flag)
        if not value:
            continue
        argv.extend([f"--{flag}", str(_resolve_flag(policy, flag, value))])
        if flag in _CONFIG_FLAGS:
            protocol_payload = json.loads(policy.read_text(value))
    if protocol_payload is not None:
        policy.assert_development_execution(protocol_payload)

    try:
        proc = subprocess.run(
            argv,
            cwd=policy.root,
            capture_output=True,
            text=True,
            timeout=spec.timeout_seconds,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"{spec.name} exceeded {spec.timeout_seconds}s and was killed."
        ) from exc

    summary = _read_output_summary(policy, args.output)
    return {
        "script": spec.name,
        "family": spec.family,
        "argv": _redact_argv(argv),
        "output": args.output,
        "returncode": proc.returncode,
        "stdout": _clip(proc.stdout),
        "stderr": _clip(proc.stderr),
        "summary": summary,
    }


def _resolve_flag(policy: RepoPolicy, flag: str, value: str) -> Any:
    if flag == "output":
        return policy.resolve_new_artifact_dir(value)
    if flag in _CONFIG_FLAGS:
        return policy.resolve_read(value)
    if flag in _DIR_FLAGS:
        return policy.resolve_existing_artifact_dir(value)
    raise PolicyError(f"Unsupported flag {flag!r}.")


def _read_output_summary(policy: RepoPolicy, output: str) -> dict[str, Any] | None:
    for name in ("preflight.json", "report.json"):
        rel = f"{output}/{name}"
        try:
            payload = json.loads(policy.read_text(rel))
        except (FileNotFoundError, PolicyError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            status = payload.get("status")
            if isinstance(payload.get("protocol"), dict):
                status = payload["protocol"].get("status") or status
            return policy.redact_reserved_test(payload, protocol_status=status if isinstance(status, str) else None)
    return None


def _clip(text: str, limit: int = 4000) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _redact_argv(argv: list[str]) -> list[str]:
    return argv


TOOLS: list[Tool] = [
    Tool(
        name="list_scripts",
        description=(
            "List the Helio24 scripts Hale is allowed to run, with required arguments and "
            "whether confirm=true is needed. Call this before run_script."
        ),
        args=ListScriptsArgs,
        handler=list_scripts,
    ),
    Tool(
        name="run_script",
        description=(
            "Run one allowlisted Helio24 script into a new artifacts/ directory. "
            "check_evaluation_protocol does not need confirm. run and audit scripts require "
            "confirm=true and an explicit user request. Never reuse an existing output path."
        ),
        args=RunScriptArgs,
        handler=run_script,
    ),
]
