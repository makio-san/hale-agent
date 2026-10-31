import sys
from pathlib import Path

from hale.policy import RepoPolicy
from hale.tools import default_registry


def invoke(policy: RepoPolicy, tool: str, **args):
    return default_registry().call(policy, tool, args)


def python_policy(repo: Path) -> RepoPolicy:
    return RepoPolicy(repo, python=Path(sys.executable))


def test_list_scripts_marks_present_wrappers(policy: RepoPolicy):
    out = invoke(policy, "list_scripts")
    assert out["ok"]
    names = {row["name"]: row for row in out["result"]["scripts"]}
    assert names["check_evaluation_protocol"]["confirm"] is False
    assert names["check_evaluation_protocol"]["present"] is True
    assert names["run_walk_forward"]["confirm"] is True
    assert names["run_walk_forward"]["family"] == "run"
    assert names["run_walk_forward"]["approval_gate"] == "protocol"
    assert names["check_evaluation_protocol"]["approval_gate"] is None


def test_check_evaluation_protocol_writes_preflight(repo: Path):
    policy = python_policy(repo)
    out = invoke(
        policy,
        "run_script",
        name="check_evaluation_protocol",
        config="config/demo-v2.json",
        output="artifacts/hale_preflight_demo",
    )
    assert out["ok"], out
    result = out["result"]
    assert result["returncode"] == 0
    assert result["summary"]["protocol_id"] == "demo"
    assert result["summary"]["final_test_allowed"] is False
    assert (repo / "artifacts" / "hale_preflight_demo" / "preflight.json").is_file()


def test_existing_output_is_denied(repo: Path):
    policy = python_policy(repo)
    first = invoke(
        policy,
        "run_script",
        name="check_evaluation_protocol",
        config="config/demo-v2.json",
        output="artifacts/hale_preflight_demo",
    )
    assert first["ok"]
    again = invoke(
        policy,
        "run_script",
        name="check_evaluation_protocol",
        config="config/demo-v2.json",
        output="artifacts/hale_preflight_demo",
    )
    assert again["error"] == "Policy violation"
    assert "already exists" in again["details"]


def test_run_family_requires_confirm(policy: RepoPolicy):
    out = invoke(
        policy,
        "run_script",
        name="run_walk_forward",
        protocol="config/demo-v2.json",
        output="artifacts/hale_walk_forward",
    )
    assert out["error"] == "Policy violation"
    assert "confirm=true" in out["details"]


def test_run_family_requires_protocol_approval(policy: RepoPolicy):
    out = invoke(
        policy,
        "run_script",
        name="run_walk_forward",
        protocol="config/demo-v2.json",
        output="artifacts/hale_walk_forward",
        confirm=True,
    )
    assert out["error"] == "Policy violation"
    assert "not approved" in out["details"]
    assert "hale approve --gate protocol" in out["details"]


def test_approved_run_reaches_the_script(repo: Path):
    policy = python_policy(repo)
    policy.write_approval("config/demo-v2.json", "protocol")
    out = invoke(
        policy,
        "run_script",
        name="run_walk_forward",
        protocol="config/demo-v2.json",
        output="artifacts/hale_walk_forward",
        confirm=True,
    )
    assert out["ok"], out
    assert out["result"]["returncode"] != 0
    assert "should not execute" in (out["result"]["stderr"] + out["result"]["stdout"])


def test_unknown_script_is_data_error(policy: RepoPolicy):
    out = invoke(policy, "run_script", name="download", output="artifacts/nope")
    assert out["error"] == "Policy violation"


def test_reserved_test_protocol_is_denied(repo: Path):
    (repo / "config" / "demo-test.json").write_text(
        '{"id": "demo", "version": 3, "status": "ok", "development_data": {"reserved_test_rows": true}}',
        encoding="utf-8",
    )
    policy = python_policy(repo)
    out = invoke(
        policy,
        "run_script",
        name="check_evaluation_protocol",
        config="config/demo-test.json",
        output="artifacts/hale_should_fail",
    )
    assert out["error"] == "Policy violation"
    assert "reserved_test_rows" in out["details"]
    assert not (repo / "artifacts" / "hale_should_fail").exists()
