from hale.config import Settings


def test_allow_git_is_opt_in(repo, monkeypatch):
    monkeypatch.setenv("HALE_TARGET_REPO", str(repo))
    monkeypatch.delenv("HALE_ALLOW_GIT", raising=False)
    assert Settings.from_env().allow_git is False
    monkeypatch.setenv("HALE_ALLOW_GIT", "1")
    assert Settings.from_env().allow_git is True
    monkeypatch.setenv("HALE_ALLOW_GIT", "0")
    assert Settings.from_env().allow_git is False
