"""Git and GitHub helpers for opening a review pull request."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Sequence

from hale.policy import PolicyError

Run = Callable[..., subprocess.CompletedProcess[str]]


class GitOps:
    def __init__(self, root: Path, run: Run | None = None) -> None:
        self.root = root
        self._run = run or subprocess.run

    def open_pull_request(
        self,
        *,
        branch: str,
        title: str,
        body: str,
        files: Sequence[str],
        message: str,
    ) -> dict[str, str]:
        self._git("rev-parse", "--is-inside-work-tree")
        self._git("checkout", "-b", branch)
        self._git("add", "--", *files)
        self._git("commit", "-m", message, "--", *files)
        self._git("push", "-u", "origin", "HEAD")
        created = self._run(
            ["gh", "pr", "create", "--title", title, "--body", body],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            raise PolicyError(created.stderr.strip() or "gh pr create failed.")
        return {"branch": branch, "url": created.stdout.strip()}

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        result = self._run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise PolicyError(result.stderr.strip() or f"git {' '.join(args)} failed.")
        return result
