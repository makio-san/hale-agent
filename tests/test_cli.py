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


def test_scripts_lists_allowlisted_wrappers(repo, capsys):
    assert main(["--repo", str(repo), "scripts"]) == 0
    out = capsys.readouterr().out
    assert "check_evaluation_protocol" in out
    assert "run_walk_forward" in out
