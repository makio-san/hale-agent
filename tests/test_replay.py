import json
from pathlib import Path

from hale.cli import main
from hale.replay import load_catalog, run_catalog, run_case


HELIO24 = Path(__file__).resolve().parents[2] / "Helio24"


def test_default_catalog_passes_without_a_live_repo():
    report = run_catalog()
    assert report.summary["failed"] == 0
    assert report.summary["passed"] == report.summary["total"]
    assert report.summary["total"] >= 10
    ids = {row.id for row in report.cases}
    assert "experiment5-v8-accept-validation-recall" in ids
    assert "hard-negative-all-year-gate-reject" in ids
    assert "inventory-no-self-approve" in ids
    assert all(
        status == "skipped"
        for row in report.cases
        for name, status in row.checks.items()
        if name.startswith("source_lock:")
    )


def test_accept_case_rejects_when_gold_is_wrong():
    catalog = load_catalog()
    case = next(item for item in catalog.cases if item.id == "experiment5-v8-accept-validation-recall")
    case.expect.decision = "reject"
    result = run_case(case)
    assert result.status == "failed"
    assert result.checks["accept_reject_match"] == "failed"


def test_source_lock_fails_when_helio24_number_changes(tmp_path: Path):
    catalog = load_catalog()
    case = next(item for item in catalog.cases if item.id == "numeric-validation-recall-exact")
    fake = tmp_path / "config"
    fake.mkdir()
    (fake / "experiment5-v8.json").write_text(
        json.dumps({"development_selection": {"validation_recall": 0.1}}),
        encoding="utf-8",
    )
    result = run_case(case, lock_repo=tmp_path)
    assert result.status == "failed"
    assert any(status == "failed" for name, status in result.checks.items() if name.startswith("source_lock:"))


def test_source_lock_passes_against_published_helio24():
    if not (HELIO24 / "config" / "experiment5-v8.json").is_file():
        return
    report = run_catalog(lock_repo=HELIO24)
    lock_statuses = [
        status
        for row in report.cases
        for name, status in row.checks.items()
        if name.startswith("source_lock:")
    ]
    assert lock_statuses
    assert "failed" not in lock_statuses
    assert report.summary["failed"] == 0


def test_cli_replay_accepts_lock_repo_after_subcommand():
    if not (HELIO24 / "config" / "experiment5-v8.json").is_file():
        return
    assert main(["replay", "--lock-repo", str(HELIO24), "--case", "numeric-validation-recall-exact"]) == 0


def test_cli_replay_json(capsys, tmp_path: Path):
    output = tmp_path / "replay.json"
    assert main(["replay", "--json", "--output", str(output), "--case", "inventory-no-self-approve"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["failed"] == 0
    assert payload["cases"][0]["id"] == "inventory-no-self-approve"
    assert json.loads(output.read_text(encoding="utf-8"))["catalog"] == "helio24-archived-decisions"


def test_cli_unknown_case_is_an_error():
    try:
        code = main(["replay", "--case", "does-not-exist"])
    except SystemExit as exc:
        assert exc.code not in {0, None}
        return
    assert code != 0
