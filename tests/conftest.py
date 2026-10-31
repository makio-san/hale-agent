import json
from pathlib import Path

import pytest

from hale.policy import RepoPolicy


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal Helio24-shaped repository."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "artifacts" / "demo_r1").mkdir(parents=True)
    (tmp_path / "data").mkdir()

    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "docs" / "demo-experiment.md").write_text(
        "# Demo experiment\n\nDevelopment recall was 0.91 on validation.\nNo test result exists.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "demo-experiment.tr.md").write_text("# Demo deneyi\n", encoding="utf-8")
    (tmp_path / "docs" / "reports.json").write_text(
        json.dumps([{"id": "demo-experiment", "en": "demo-experiment.md", "tr": "demo-experiment.tr.md"}]),
        encoding="utf-8",
    )
    (tmp_path / "config" / "demo-v1.json").write_text(
        json.dumps({"id": "demo", "version": 1, "status": "design_frozen"}), encoding="utf-8"
    )
    (tmp_path / "config" / "demo-v2.json").write_text(
        json.dumps(
            {
                "id": "demo",
                "version": 2,
                "status": "development_selection_frozen_test_pending",
                "supersedes": "config/demo-v1.json",
                "roles": {"train": ["2010", "2022"], "test": ["2024", "2026"]},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "artifacts" / "demo_r1" / "report.json").write_text(
        json.dumps(
            {
                "protocol": {"id": "demo", "status": "development_selection_frozen_test_pending"},
                "metrics": {"validation": {"recall": 0.91}, "test": {"recall": 0.5}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "artifacts" / "demo_r1" / "metrics.csv").write_text(
        "role,recall\nvalidation,0.91\ntest,0.5\n", encoding="utf-8"
    )
    (tmp_path / "data" / "secret.csv").write_text("label\n1\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def policy(repo: Path) -> RepoPolicy:
    return RepoPolicy(repo)
