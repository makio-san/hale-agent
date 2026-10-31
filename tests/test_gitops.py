import subprocess

from hale.gitops import GitOps
from hale.policy import PolicyError, RepoPolicy
from hale.tools import default_registry


def invoke(policy: RepoPolicy, name: str, **args):
    return default_registry().call(policy, name, args)


class FakeRun:
    def __init__(self, gh_url="https://github.com/makio-san/helio24/pull/1\n"):
        self.calls: list[list[str]] = []
        self.gh_url = gh_url

    def __call__(self, argv, **_kwargs):
        self.calls.append(list(argv))
        if argv[:2] == ["gh", "pr"]:
            return subprocess.CompletedProcess(argv, 0, stdout=self.gh_url, stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")


def test_gitops_opens_pr_without_merging(repo):
    runner = FakeRun()
    result = GitOps(repo, run=runner).open_pull_request(
        branch="hale/demo-v3",
        title="Add demo v3 protocol",
        body="Review only.",
        files=["config/demo-v2.json", "docs/demo-experiment.md"],
        message="feat(config): add demo v3 protocol.",
    )
    assert result["url"] == "https://github.com/makio-san/helio24/pull/1"
    assert result["branch"] == "hale/demo-v3"
    commands = [" ".join(call) for call in runner.calls]
    assert "git checkout -b hale/demo-v3" in commands
    assert "git commit -m feat(config): add demo v3 protocol. -- config/demo-v2.json docs/demo-experiment.md" in commands
    assert "git push -u origin HEAD" in commands
    assert "gh pr create --title Add demo v3 protocol --body Review only." in commands
    assert not any("merge" in " ".join(call) for call in runner.calls)


def test_open_pull_request_tool_uses_gitops(policy: RepoPolicy, repo, monkeypatch):
    policy.write_approval(
        "config/demo-v2.json",
        "pull_request",
        ["docs/demo-experiment.md"],
    )
    git_policy = RepoPolicy(repo, allow_git=True)
    captured = {}

    class FakeGitOps:
        def __init__(self, root):
            captured["root"] = root

        def open_pull_request(self, **kwargs):
            captured.update(kwargs)
            return {"branch": kwargs["branch"], "url": "https://example.test/pr/1"}

    monkeypatch.setattr("hale.tools.loop.GitOps", FakeGitOps)
    out = invoke(
        git_policy,
        "open_pull_request",
        branch="hale/demo-v3",
        title="Add demo v3 protocol",
        body="Review only. Do not merge yet.",
        message="feat(config): add demo v3 protocol.",
        files=["config/demo-v2.json", "docs/demo-experiment.md"],
        confirm=True,
    )
    assert out["ok"], out
    assert captured["files"] == ["config/demo-v2.json", "docs/demo-experiment.md"]
    assert out["result"]["url"] == "https://example.test/pr/1"


def test_open_pull_request_rejects_unapproved_file_set(repo):
    policy = RepoPolicy(repo, allow_git=True)
    policy.write_approval("config/demo-v2.json", "pull_request")
    out = invoke(
        policy,
        "open_pull_request",
        branch="hale/demo-v3",
        title="Add demo v3 protocol",
        body="Review only.",
        message="feat(config): add demo v3 protocol.",
        files=["config/demo-v2.json", "docs/demo-experiment.md"],
        confirm=True,
    )
    assert out["error"] == "Policy violation"
    assert "not in the pull_request approval set" in out["details"]


def test_open_pull_request_rejects_invalid_commit_message(repo):
    policy = RepoPolicy(repo, allow_git=True)
    out = invoke(
        policy,
        "open_pull_request",
        branch="hale/demo-v3",
        title="Add demo v3 protocol",
        body="Review only.",
        message="added files",
        files=["config/demo-v2.json"],
        confirm=True,
    )
    assert out["error"] == "Policy violation"
    assert "Commit message" in out["details"]
