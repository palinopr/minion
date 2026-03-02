"""Git worktree management -- Mac Mini alternative to devbox sandboxes.

Instead of spinning up EC2 instances like Stripe, we use git worktrees.
Each agent gets its own working copy of the repo on a separate branch.
This gives isolation without VMs or containers.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class Worktree:
    """Manage an isolated git worktree for an agent run."""

    def __init__(self, repo_path: Path, branch: str, base_branch: str = "main"):
        self.repo_path = repo_path
        self.branch = branch
        self.base_branch = base_branch
        self.worktree_path = repo_path.parent / f".worktrees/{branch}"

    # Patterns that should always be gitignored in agent worktrees
    DEFAULT_IGNORES = [
        "__pycache__/",
        "*.pyc",
        ".pytest_cache/",
        "node_modules/",
        ".DS_Store",
        "*.egg-info/",
        ".env",
        "dist/",
        "build/",
    ]

    def create(self) -> Path:
        """Create a worktree on a new branch. Returns the worktree path."""
        self.worktree_path.parent.mkdir(parents=True, exist_ok=True)

        subprocess.run(
            ["git", "worktree", "add", "-b", self.branch, str(self.worktree_path), self.base_branch],
            cwd=self.repo_path,
            check=True,
            capture_output=True,
            text=True,
        )

        self._ensure_gitignore()
        return self.worktree_path

    def _ensure_gitignore(self) -> None:
        """Make sure common junk patterns are gitignored in the worktree."""
        gitignore = self.worktree_path / ".gitignore"
        existing = set()
        if gitignore.exists():
            existing = set(gitignore.read_text().splitlines())

        missing = [p for p in self.DEFAULT_IGNORES if p not in existing]
        if missing:
            with open(gitignore, "a") as f:
                if existing and not gitignore.read_text().endswith("\n"):
                    f.write("\n")
                f.write("# Added by minion\n")
                for pattern in missing:
                    f.write(f"{pattern}\n")

    def cleanup(self) -> None:
        """Remove the worktree and branch."""
        try:
            subprocess.run(
                ["git", "worktree", "remove", str(self.worktree_path), "--force"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            pass

        try:
            subprocess.run(
                ["git", "branch", "-D", self.branch],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            pass

    def has_remote(self) -> bool:
        """Check if the repo has a remote configured."""
        result = subprocess.run(
            ["git", "remote"],
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())

    def commit(self, message: str) -> bool:
        """Stage all changes and commit. Returns True if there were changes."""
        wt = str(self.worktree_path)

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=wt, capture_output=True, text=True,
        )
        if not status.stdout.strip():
            return False

        subprocess.run(["git", "add", "-A"], cwd=wt, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=wt, check=True, capture_output=True, text=True,
        )
        return True

    def push(self) -> bool:
        """Push the branch to origin. Returns True on success, False if no remote."""
        if not self.has_remote():
            return False

        try:
            subprocess.run(
                ["git", "push", "-u", "origin", self.branch],
                cwd=str(self.worktree_path),
                check=True, capture_output=True, text=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            print(f"  Push failed: {e.stderr.strip()}")
            return False

    def commit_and_push(self, message: str) -> bool:
        """Stage, commit, and push if remote exists. Returns True if committed."""
        if not self.commit(message):
            return False
        self.push()
        return True

    def create_pr(self, title: str, body: str, reviewer: str = "") -> str | None:
        """Create a GitHub PR. Returns the PR URL or None."""
        if not self.has_remote():
            print("  No remote configured -- skipping PR creation.")
            print(f"  Branch '{self.branch}' is ready for review locally.")
            return None

        cmd = [
            "gh", "pr", "create",
            "--title", title,
            "--body", body,
            "--base", self.base_branch,
            "--head", self.branch,
        ]
        if reviewer:
            cmd.extend(["--reviewer", reviewer])

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.worktree_path),
                check=True, capture_output=True, text=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"  Failed to create PR: {e.stderr.strip()}")
            return None

    def get_diff_summary(self) -> str:
        """Get a summary of changes in the worktree branch vs base."""
        try:
            result = subprocess.run(
                ["git", "diff", "--stat", f"{self.base_branch}...{self.branch}"],
                cwd=str(self.repo_path),
                capture_output=True, text=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return ""
