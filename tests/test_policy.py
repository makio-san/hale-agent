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
