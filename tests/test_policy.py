import os
from pathlib import Path

import pytest

from hale.policy import PolicyError, RepoPolicy


def test_allowlisted_paths_resolve(policy: RepoPolicy, repo: Path):
    assert policy.resolve_read("README.md") == (repo / "README.md").resolve()
    assert policy.resolve_read("docs/demo-experiment.md").is_file()
    assert policy.resolve_read("config/demo-v2.json").is_file()
    assert policy.resolve_read("artifacts/demo_r1/report.json").is_file()


@pytest.mark.parametrize(
    "path",
    ["data/secret.csv", "../outside.md", "/etc/passwd", "~/x.md", "docs/../data/secret.csv", "artifacts/demo_r1/model.pkl"],
)
def test_denied_paths_raise(policy: RepoPolicy, path: str):
    with pytest.raises(PolicyError):
        policy.resolve_read(path)


def test_symlink_escape_is_denied(policy: RepoPolicy, repo: Path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "leak.md"
    outside.write_text("secret", encoding="utf-8")
    link = repo / "docs" / "leak.md"
    os.symlink(outside, link)
    with pytest.raises(PolicyError):
        policy.resolve_read("docs/leak.md")


def test_missing_allowed_file_is_not_found(policy: RepoPolicy):
    with pytest.raises(FileNotFoundError):
        policy.resolve_read("docs/nope.md")


def test_reserved_test_sections_are_redacted(policy: RepoPolicy):
    payload = {"metrics": {"validation": {"recall": 0.9}, "test": {"recall": 0.5}, "final_test_ap": 0.1}}
    out = policy.redact_reserved_test(payload, protocol_status="development_selection_frozen_test_pending")
    assert out["metrics"]["validation"] == {"recall": 0.9}
    assert out["metrics"]["test"].startswith("[redacted")
    assert out["metrics"]["final_test_ap"].startswith("[redacted")


def test_permission_flags_are_not_redacted(policy: RepoPolicy):
    payload = {"final_test_allowed": False, "test": {"recall": 0.5}}
    out = policy.redact_reserved_test(payload)
    assert out["final_test_allowed"] is False
    assert out["test"].startswith("[redacted")


def test_redaction_lifts_when_final_test_is_complete(policy: RepoPolicy):
    payload = {"test": {"recall": 0.5}}
    assert policy.redact_reserved_test(payload, protocol_status="final_test_complete") == payload


def test_redaction_lifts_with_explicit_override(repo: Path):
    policy = RepoPolicy(repo, allow_test_role=True)
    payload = {"test": {"recall": 0.5}}
    assert policy.redact_reserved_test(payload) == payload


@pytest.mark.parametrize("dotted", ["metrics.test.recall", "test", "results.reserved_test_2024", "final_test.ap"])
def test_metric_paths_to_test_role_are_denied(policy: RepoPolicy, dotted: str):
    with pytest.raises(PolicyError):
        policy.check_metric_path(dotted)


def test_metric_paths_to_development_roles_pass(policy: RepoPolicy):
    policy.check_metric_path("metrics.validation.recall")
    policy.check_metric_path("protocol.status")


def test_new_artifact_directory_must_not_exist(policy: RepoPolicy, repo: Path):
    path = policy.resolve_new_artifact_dir("artifacts/hale_preflight_demo")
    assert path == repo / "artifacts" / "hale_preflight_demo"
    assert not path.exists()
    path.mkdir()
    with pytest.raises(PolicyError):
        policy.resolve_new_artifact_dir("artifacts/hale_preflight_demo")


@pytest.mark.parametrize("path", ["artifacts/../config", "docs/out", "artifacts/nested/dir", "/tmp/out"])
def test_new_artifact_directory_rejects_escapes(policy: RepoPolicy, path: str):
    with pytest.raises(PolicyError):
        policy.resolve_new_artifact_dir(path)


def test_unknown_script_is_denied(policy: RepoPolicy):
    with pytest.raises(PolicyError):
        policy.resolve_script("download", {"check_evaluation_protocol"})


def test_reserved_test_rows_block_execution(policy: RepoPolicy):
    with pytest.raises(PolicyError):
        policy.assert_development_execution({"development_data": {"reserved_test_rows": True}})
    policy.assert_development_execution({"status": "development_selection_frozen_test_pending"})


def test_reserved_test_labels_match_role_names(policy: RepoPolicy):
    assert policy.is_reserved_test_label("test")
    assert policy.is_reserved_test_label("reserved_test_2024")
    assert not policy.is_reserved_test_label("validation")
    assert not policy.is_reserved_test_label("test", protocol_status="final_test_complete")


def test_write_new_file_is_create_only(policy: RepoPolicy, repo: Path):
    path = policy.write_new_file("config/demo-v3.json", '{"id": "demo", "version": 3}\n')
    assert path == repo / "config" / "demo-v3.json"
    with pytest.raises(PolicyError, match="already exists"):
        policy.write_new_file("config/demo-v3.json", '{"id": "demo", "version": 3}\n')
    with pytest.raises(PolicyError):
        policy.write_new_file("docs/secret.txt", "nope\n")
    with pytest.raises(PolicyError):
        policy.write_new_file("config/demo-v2.json", "{}\n")


def test_protocol_approval_binds_hash(policy: RepoPolicy, repo: Path):
    recorded = policy.write_approval("config/demo-v2.json", "protocol")
    assert recorded.name.startswith("protocol-")
    policy.require_approval("config/demo-v2.json", "protocol")
    (repo / "config" / "demo-v2.json").write_text('{"id": "demo", "version": 2, "edited": true}', encoding="utf-8")
    with pytest.raises(PolicyError, match="changed after approval"):
        policy.require_approval("config/demo-v2.json", "protocol")


def test_git_operations_default_denied(policy: RepoPolicy):
    with pytest.raises(PolicyError, match="HALE_ALLOW_GIT"):
        policy.assert_git_allowed()
    RepoPolicy(policy.root, allow_git=True).assert_git_allowed()
