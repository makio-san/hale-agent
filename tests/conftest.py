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
    (tmp_path / "config" / "swan_sf_v2_sources.verified.json").write_text(
        json.dumps({"id": "swan-sf-v2-preprint-v1-2026-10-01", "status": "verified"}),
        encoding="utf-8",
    )
    (tmp_path / "config" / "demo-v2.json").write_text(
        json.dumps(
            {
                "id": "demo",
                "version": 2,
                "status": "development_selection_frozen_test_pending",
                "supersedes": "config/demo-v1.json",
                "evidence_files": ["docs/demo-experiment.md", "docs/demo-experiment.tr.md"],
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
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_evaluation_protocol.py").write_text(
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
        "    'protocol_version': protocol.get('version'),\n"
        "    'ready_for_training': False,\n"
        "    'final_test_allowed': False,\n"
        "    'note': 'fixture preflight',\n"
        "}) + '\\n')\n"
        "print('preflight written')\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "run_walk_forward.py").write_text(
        "raise SystemExit('run_walk_forward stub should not execute in tests')\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def policy(repo: Path) -> RepoPolicy:
    return RepoPolicy(repo)
