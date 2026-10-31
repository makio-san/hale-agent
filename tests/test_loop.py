import json

from hale.policy import RepoPolicy
from hale.tools import default_registry


def invoke(policy: RepoPolicy, name: str, **args):
    return default_registry().call(policy, name, args)


PROPOSE = {
    "base": "config/demo-v2.json",
    "hypothesis": "A later calibration window will keep validation recall.",
    "acceptance_description": "Validation recall must stay at least 0.90.",
    "metric_path": "metrics.validation.recall",
    "op": ">=",
    "value": 0.90,
    "revision_reason": "Need a frozen rule before the next development fit.",
}

EN_REPORT = """# Demo calibration

| metric | value |
| --- | --- |
| recall | 0.91 |
| false positives | 12 |
"""

TR_REPORT = """# Demo kalibrasyonu

| metrik | deger |
| --- | --- |
| recall | 0.91 |
| yanlis pozitif | 12 |
"""


def test_registry_exposes_stage_three_tools():
    names = default_registry().names()
    assert names == [
        "draft_report",
        "get_experiment",
        "interpret_result",
        "list_experiments",
        "list_scripts",
        "open_pull_request",
        "propose_protocol",
        "read_artifact",
        "read_document",
        "register_report",
        "run_script",
        "search_reports",
    ]
    assert "write_approval" not in names


def test_propose_protocol_writes_next_version(policy: RepoPolicy, repo):
    out = invoke(policy, "propose_protocol", **PROPOSE)
    assert out["ok"], out
    path = repo / "config" / "demo-v3.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 3
    assert payload["status"] == "design_proposed"
    assert payload["supersedes"] == "config/demo-v2.json"
    assert payload["hypothesis"] == PROPOSE["hypothesis"]
    assert payload["acceptance_rule"]["value"] == 0.90
    assert "approved" not in payload
    assert out["result"]["approved"] is False
    assert "hale approve --gate protocol" in out["result"]["note"]


def test_propose_protocol_rejects_frozen_fields(policy: RepoPolicy):
    out = invoke(policy, "propose_protocol", **PROPOSE, changes={"roles": {"train": ["2011"]}})
    assert out["error"] == "Policy violation"
    assert "frozen fields" in out["details"]


def test_propose_protocol_forces_reserved_test_rows_false(policy: RepoPolicy, repo):
    (repo / "config" / "demo-v2.json").write_text(
        json.dumps(
            {
                "id": "demo",
                "version": 2,
                "status": "ok",
                "development_data": {"reserved_test_rows": True},
            }
        ),
        encoding="utf-8",
    )
    out = invoke(policy, "propose_protocol", **PROPOSE)
    assert out["ok"], out
    payload = json.loads((repo / "config" / "demo-v3.json").read_text(encoding="utf-8"))
    assert payload["development_data"]["reserved_test_rows"] is False


def test_propose_protocol_cannot_overwrite_existing(policy: RepoPolicy, repo):
    assert invoke(policy, "propose_protocol", **PROPOSE)["ok"]
    again = invoke(policy, "propose_protocol", **PROPOSE)
    assert again["error"] == "Policy violation"
    assert "already exists" in again["details"]


def test_propose_protocol_denies_test_metric_path(policy: RepoPolicy):
    args = dict(PROPOSE, metric_path="metrics.test.recall")
    out = invoke(policy, "propose_protocol", **args)
    assert out["error"] == "Policy violation"


def test_interpret_result_accepts_frozen_rule(policy: RepoPolicy):
    assert invoke(policy, "propose_protocol", **PROPOSE)["ok"]
    out = invoke(
        policy,
        "interpret_result",
        protocol="config/demo-v3.json",
        artifact="artifacts/demo_r1",
    )
    assert out["ok"], out
    assert out["result"]["decision"] == "accept"
    assert out["result"]["observed"] == 0.91


def test_interpret_result_rejects_failed_rule(policy: RepoPolicy):
    args = dict(PROPOSE, value=0.95)
    assert invoke(policy, "propose_protocol", **args)["ok"]
    out = invoke(
        policy,
        "interpret_result",
        protocol="config/demo-v3.json",
        artifact="artifacts/demo_r1",
    )
    assert out["result"]["decision"] == "reject"
    assert out["result"]["observed"] == 0.91


def test_interpret_result_does_not_use_redacted_test_metrics(policy: RepoPolicy, repo):
    assert invoke(policy, "propose_protocol", **PROPOSE)["ok"]
    protocol = json.loads((repo / "config" / "demo-v3.json").read_text(encoding="utf-8"))
    protocol["acceptance_rule"]["metric_path"] = "metrics.validation.recall"
    (repo / "config" / "demo-v3.json").write_text(json.dumps(protocol), encoding="utf-8")
    report = json.loads((repo / "artifacts" / "demo_r1" / "report.json").read_text(encoding="utf-8"))
    report["metrics"]["validation"]["recall"] = 0.1
    report["metrics"]["test"]["recall"] = 0.99
    (repo / "artifacts" / "demo_r1" / "report.json").write_text(json.dumps(report), encoding="utf-8")
    out = invoke(
        policy,
        "interpret_result",
        protocol="config/demo-v3.json",
        artifact="artifacts/demo_r1",
    )
    assert out["result"]["decision"] == "reject"
    assert out["result"]["observed"] == 0.1


def test_draft_report_requires_numeric_parity(policy: RepoPolicy, repo):
    bad = invoke(
        policy,
        "draft_report",
        report_id="demo-calibration",
        en_markdown=EN_REPORT,
        tr_markdown=TR_REPORT.replace("0.91", "0.92"),
    )
    assert bad["error"] == "Policy violation"
    assert "Numeric table cells" in bad["details"]
    assert not (repo / "docs" / "demo-calibration.md").exists()


def test_draft_and_register_report_are_append_only(policy: RepoPolicy, repo):
    original = (repo / "docs" / "reports.json").read_text(encoding="utf-8")
    draft = invoke(
        policy,
        "draft_report",
        report_id="demo-calibration",
        en_markdown=EN_REPORT,
        tr_markdown=TR_REPORT,
    )
    assert draft["ok"], draft
    registered = invoke(policy, "register_report", report_id="demo-calibration")
    assert registered["ok"], registered
    catalog = json.loads((repo / "docs" / "reports.json").read_text(encoding="utf-8"))
    assert catalog[0] == json.loads(original)[0]
    assert catalog[-1]["id"] == "demo-calibration"
    assert catalog[-1]["en"] == "demo-calibration.md"
    assert catalog[-1]["tr"] == "demo-calibration.tr.md"
    again = invoke(policy, "register_report", report_id="demo-calibration")
    assert again["error"] == "Policy violation"
    overwrite = invoke(
        policy,
        "draft_report",
        report_id="demo-calibration",
        en_markdown=EN_REPORT,
        tr_markdown=TR_REPORT,
    )
    assert overwrite["error"] == "Policy violation"


def test_open_pull_request_needs_confirm_git_flag_and_approval(policy: RepoPolicy):
    files = ["config/demo-v2.json"]
    denied = invoke(
        policy,
        "open_pull_request",
        branch="hale/demo-v3",
        title="Add demo v3 protocol",
        body="Review only. Do not merge yet.",
        message="feat(config): add demo v3 protocol.",
        files=files,
        confirm=True,
    )
    assert denied["error"] == "Policy violation"
    assert "HALE_ALLOW_GIT" in denied["details"]
