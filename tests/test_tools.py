from hale.policy import RepoPolicy
from hale.tools import default_registry


def call(policy: RepoPolicy, name: str, **args):
    return default_registry().call(policy, name, args)


def test_registry_exposes_stage_one_tools():
    assert default_registry().names() == [
        "get_experiment",
        "list_experiments",
        "list_scripts",
        "read_artifact",
        "read_document",
        "run_script",
        "search_reports",
    ]


def test_schemas_are_json_schema(policy: RepoPolicy):
    for schema in default_registry().schemas():
        assert schema["input_schema"]["type"] == "object"
        assert schema["description"]


def test_list_experiments_groups_versions(policy: RepoPolicy):
    out = call(policy, "list_experiments")
    assert out["ok"]
    exp = out["result"]["experiments"][0]
    assert exp["id"] == "demo"
    assert exp["latest_version"] == 2
    assert exp["status"] == "development_selection_frozen_test_pending"
    assert exp["versions"] == ["config/demo-v1.json", "config/demo-v2.json"]
    assert out["result"]["count"] == 1


def test_get_experiment_returns_protocol_and_related_reports(policy: RepoPolicy):
    out = call(policy, "get_experiment", path="config/demo-v2.json")
    assert out["ok"]
    assert out["result"]["protocol"]["supersedes"] == "config/demo-v1.json"
    assert out["result"]["protocol"]["roles"]["test"] == ["2024", "2026"]  # metadata stays readable
    assert out["result"]["related_reports"][0]["id"] == "demo-experiment"
    assert out["result"]["evidence_files"] == ["docs/demo-experiment.md", "docs/demo-experiment.tr.md"]


def test_search_reports_returns_locations(policy: RepoPolicy):
    out = call(policy, "search_reports", query="recall was")
    assert out["ok"]
    hit = out["result"]["hits"][0]
    assert hit["path"] == "docs/demo-experiment.md"
    assert hit["line"] == 3


def test_read_document_slices_lines(policy: RepoPolicy):
    out = call(policy, "read_document", path="docs/demo-experiment.md", start_line=3, max_lines=1)
    assert out["ok"]
    assert out["result"]["text"] == "Development recall was 0.91 on validation."
    assert out["result"]["total_lines"] == 4


def test_read_artifact_redacts_test_role(policy: RepoPolicy):
    out = call(policy, "read_artifact", artifact="demo_r1", path="metrics", metrics_rows=5)
    assert out["ok"]
    value = out["result"]["value"]
    assert value["validation"] == {"recall": 0.91}
    assert value["test"].startswith("[redacted")
    rows = out["result"]["metrics"]["rows"]
    assert rows == [{"role": "validation", "recall": "0.91"}]
    assert out["result"]["metrics"]["redacted_rows"] == 1


def test_read_artifact_denies_direct_test_path(policy: RepoPolicy):
    out = call(policy, "read_artifact", artifact="demo_r1", path="metrics.test.recall")
    assert not out["ok"]
    assert out["error"] == "Policy violation"


def test_tools_return_errors_as_data(policy: RepoPolicy):
    assert call(policy, "read_document", path="data/secret.csv")["error"] == "Policy violation"
    assert call(policy, "read_document", path="docs/missing.md")["error"] == "Not found"
    assert call(policy, "read_document")["error"] == "Invalid arguments"
    assert call(policy, "nope")["error"].startswith("Unknown tool")
