from hale.cli import main


def test_experiments_lists_fixture_protocols(repo, capsys):
    assert main(["--repo", str(repo), "experiments"]) == 0
    out = capsys.readouterr().out
    assert "demo" in out
    assert "development_selection_frozen_test_pending" in out
    assert "config/demo-v2.json" in out


def test_tools_lists_stage_one_names(capsys):
    assert main(["tools"]) == 0
    out = capsys.readouterr().out
    assert "list_experiments" in out
    assert "read_artifact" in out
    assert "run_script" in out
    assert "propose_protocol" in out
    assert "open_pull_request" in out


def test_replay_lists_bundled_cases(capsys):
    assert main(["replay", "--case", "inventory-no-self-approve"]) == 0
    out = capsys.readouterr().out
    assert "inventory-no-self-approve" in out
    assert "passed" in out


def test_scripts_lists_allowlisted_wrappers(repo, capsys):
    assert main(["--repo", str(repo), "scripts"]) == 0
    out = capsys.readouterr().out
    assert "check_evaluation_protocol" in out
    assert "run_walk_forward" in out


def test_approve_records_protocol_gate(repo, capsys):
    assert main(["--repo", str(repo), "approve", "--gate", "protocol", "config/demo-v2.json"]) == 0
    recorded = capsys.readouterr().out.strip()
    assert recorded == "artifacts/hale_approvals/protocol-config__demo-v2_json.json"
    assert (repo / recorded).is_file()
    assert main(["--repo", str(repo), "proposals"]) == 0
    listed = capsys.readouterr().out
    assert recorded in listed
