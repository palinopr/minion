"""Tests for minion.worktree -- git worktree management."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from minion.worktree import Worktree


@pytest.fixture
def wt(tmp_path: Path) -> Worktree:
    """Create a Worktree instance with a tmp_path repo."""
    return Worktree(repo_path=tmp_path / "repo", branch="agent/fix-123", base_branch="main")


# ── __init__ ─────────────────────────────────────────────────────────


class TestWorktreeInit:
    def test_worktree_path_derived_from_repo(self, wt: Worktree):
        assert wt.worktree_path == wt.repo_path.parent / ".worktrees/agent/fix-123"

    def test_stores_branch(self, wt: Worktree):
        assert wt.branch == "agent/fix-123"

    def test_stores_base_branch(self, wt: Worktree):
        assert wt.base_branch == "main"

    def test_default_base_branch(self, tmp_path: Path):
        w = Worktree(tmp_path, "feat")
        assert w.base_branch == "main"


# ── create ───────────────────────────────────────────────────────────


class TestCreate:
    @patch("minion.worktree.subprocess.run")
    def test_calls_git_worktree_add(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(returncode=0)
        wt.worktree_path.mkdir(parents=True, exist_ok=True)
        wt.create()
        git_call = mock_run.call_args_list[0]
        assert git_call[0][0][:3] == ["git", "worktree", "add"]

    @patch("minion.worktree.subprocess.run")
    def test_creates_parent_directory(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(returncode=0)
        wt.worktree_path.mkdir(parents=True, exist_ok=True)
        wt.create()
        assert wt.worktree_path.parent.exists()

    @patch("minion.worktree.subprocess.run")
    def test_returns_worktree_path(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(returncode=0)
        wt.worktree_path.mkdir(parents=True, exist_ok=True)
        result = wt.create()
        assert result == wt.worktree_path

    @patch("minion.worktree.subprocess.run")
    def test_passes_branch_and_base(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(returncode=0)
        wt.worktree_path.mkdir(parents=True, exist_ok=True)
        wt.create()
        cmd = mock_run.call_args_list[0][0][0]
        assert "-b" in cmd
        assert wt.branch in cmd
        assert wt.base_branch in cmd


# ── _ensure_gitignore ────────────────────────────────────────────────


class TestEnsureGitignore:
    @patch("minion.worktree.subprocess.run")
    def test_creates_gitignore_with_defaults(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(returncode=0)
        wt.worktree_path.mkdir(parents=True)
        wt._ensure_gitignore()
        gitignore = wt.worktree_path / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert "__pycache__/" in content
        assert "node_modules/" in content

    @patch("minion.worktree.subprocess.run")
    def test_does_not_duplicate_existing_patterns(self, mock_run: MagicMock, wt: Worktree):
        wt.worktree_path.mkdir(parents=True)
        gitignore = wt.worktree_path / ".gitignore"
        gitignore.write_text("__pycache__/\n")
        wt._ensure_gitignore()
        content = gitignore.read_text()
        assert content.count("__pycache__/") == 1

    @patch("minion.worktree.subprocess.run")
    def test_appends_missing_patterns(self, mock_run: MagicMock, wt: Worktree):
        wt.worktree_path.mkdir(parents=True)
        gitignore = wt.worktree_path / ".gitignore"
        gitignore.write_text("__pycache__/\n")
        wt._ensure_gitignore()
        content = gitignore.read_text()
        assert "node_modules/" in content
        assert ".DS_Store" in content


# ── _link_dependencies ───────────────────────────────────────────────


class TestLinkDependencies:
    def test_symlinks_node_modules_when_present(self, wt: Worktree):
        wt.repo_path.mkdir(parents=True)
        (wt.repo_path / "node_modules").mkdir()
        wt.worktree_path.mkdir(parents=True)
        wt._link_dependencies()
        link = wt.worktree_path / "node_modules"
        assert link.is_symlink()

    def test_skips_when_source_absent(self, wt: Worktree):
        wt.repo_path.mkdir(parents=True)
        wt.worktree_path.mkdir(parents=True)
        wt._link_dependencies()  # should not crash
        assert not (wt.worktree_path / "node_modules").exists()

    def test_skips_when_target_already_exists(self, wt: Worktree):
        wt.repo_path.mkdir(parents=True)
        (wt.repo_path / "node_modules").mkdir()
        wt.worktree_path.mkdir(parents=True)
        (wt.worktree_path / "node_modules").mkdir()
        wt._link_dependencies()  # should not crash or overwrite
        assert not (wt.worktree_path / "node_modules").is_symlink()


# ── cleanup ──────────────────────────────────────────────────────────


class TestCleanup:
    @patch("minion.worktree.subprocess.run")
    def test_calls_worktree_remove(self, mock_run: MagicMock, wt: Worktree):
        wt.cleanup()
        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert any("worktree" in cmd and "remove" in cmd for cmd in cmds)

    @patch("minion.worktree.subprocess.run")
    def test_calls_branch_delete(self, mock_run: MagicMock, wt: Worktree):
        wt.cleanup()
        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert any("branch" in cmd and "-D" in cmd for cmd in cmds)

    @patch("minion.worktree.subprocess.run", side_effect=subprocess.CalledProcessError(1, "git"))
    def test_does_not_raise_on_failure(self, mock_run: MagicMock, wt: Worktree):
        wt.cleanup()  # should silently swallow errors


# ── commit ───────────────────────────────────────────────────────────


class TestCommit:
    @patch("minion.worktree.subprocess.run")
    def test_returns_false_when_no_changes(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        assert wt.commit("msg") is False

    @patch("minion.worktree.subprocess.run")
    def test_returns_true_when_changes_exist(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(stdout=" M file.py\n", returncode=0)
        assert wt.commit("msg") is True

    @patch("minion.worktree.subprocess.run")
    def test_stages_and_commits(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(stdout=" M file.py\n", returncode=0)
        wt.commit("fix: stuff")
        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert ["git", "add", "-A"] in cmds
        assert any("commit" in cmd and "fix: stuff" in cmd for cmd in cmds)

    @patch("minion.worktree.subprocess.run")
    def test_uses_worktree_path_as_cwd(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(stdout=" M file.py\n", returncode=0)
        wt.commit("msg")
        for c in mock_run.call_args_list:
            assert c.kwargs.get("cwd") == str(wt.worktree_path)


# ── has_remote ───────────────────────────────────────────────────────


class TestHasRemote:
    @patch("minion.worktree.subprocess.run")
    def test_true_when_remote_exists(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(stdout="origin\n")
        assert wt.has_remote() is True

    @patch("minion.worktree.subprocess.run")
    def test_false_when_no_remote(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(stdout="")
        assert wt.has_remote() is False

    @patch("minion.worktree.subprocess.run")
    def test_false_when_only_whitespace(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(stdout="  \n")
        assert wt.has_remote() is False


# ── push ─────────────────────────────────────────────────────────────


class TestPush:
    @patch("minion.worktree.subprocess.run")
    def test_returns_false_without_remote(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(stdout="")  # no remote
        assert wt.push() is False

    @patch("minion.worktree.subprocess.run")
    def test_returns_true_on_successful_push(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(stdout="origin\n", returncode=0)
        assert wt.push() is True

    @patch("minion.worktree.subprocess.run")
    def test_returns_false_when_push_fails(self, mock_run: MagicMock, wt: Worktree):
        def side_effect(cmd, **kwargs):
            if "push" in cmd:
                raise subprocess.CalledProcessError(1, "git", stderr="denied")
            return MagicMock(stdout="origin\n")
        mock_run.side_effect = side_effect
        assert wt.push() is False


# ── merge_pr ─────────────────────────────────────────────────────────


class TestMergePR:
    @patch("minion.worktree.subprocess.run")
    def test_returns_true_on_success(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(returncode=0)
        assert wt.merge_pr("https://github.com/o/r/pull/1") is True

    @patch("minion.worktree.subprocess.run")
    def test_calls_gh_pr_merge(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(returncode=0)
        url = "https://github.com/o/r/pull/1"
        wt.merge_pr(url)
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["gh", "pr", "merge"]
        assert url in cmd
        assert "--delete-branch" in cmd

    def test_returns_false_for_empty_url(self, wt: Worktree):
        assert wt.merge_pr("") is False

    def test_returns_false_for_none_url(self, wt: Worktree):
        assert wt.merge_pr(None) is False

    @patch("minion.worktree.subprocess.run", side_effect=subprocess.CalledProcessError(1, "gh", stderr="nope"))
    def test_returns_false_on_failure(self, mock_run: MagicMock, wt: Worktree):
        assert wt.merge_pr("https://github.com/o/r/pull/1") is False


# ── create_pr ────────────────────────────────────────────────────────


class TestCreatePR:
    @patch("minion.worktree.subprocess.run")
    def test_returns_pr_url_on_success(self, mock_run: MagicMock, wt: Worktree):
        def side_effect(cmd, **kwargs):
            if "remote" in cmd:
                return MagicMock(stdout="origin\n")
            return MagicMock(stdout="https://github.com/o/r/pull/42\n", returncode=0)
        mock_run.side_effect = side_effect
        url = wt.create_pr("title", "body")
        assert url == "https://github.com/o/r/pull/42"

    @patch("minion.worktree.subprocess.run")
    def test_returns_none_without_remote(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(stdout="")
        assert wt.create_pr("title", "body") is None

    @patch("minion.worktree.subprocess.run")
    def test_includes_reviewer_when_specified(self, mock_run: MagicMock, wt: Worktree):
        def side_effect(cmd, **kwargs):
            if "remote" in cmd:
                return MagicMock(stdout="origin\n")
            return MagicMock(stdout="https://github.com/o/r/pull/1\n", returncode=0)
        mock_run.side_effect = side_effect
        wt.create_pr("title", "body", reviewer="alice")
        gh_call = [c for c in mock_run.call_args_list if "gh" in c[0][0]][-1]
        assert "--reviewer" in gh_call[0][0]
        assert "alice" in gh_call[0][0]

    @patch("minion.worktree.subprocess.run")
    def test_returns_none_on_gh_failure(self, mock_run: MagicMock, wt: Worktree):
        def side_effect(cmd, **kwargs):
            if "remote" in cmd:
                return MagicMock(stdout="origin\n")
            raise subprocess.CalledProcessError(1, "gh", stderr="fail")
        mock_run.side_effect = side_effect
        assert wt.create_pr("title", "body") is None


# ── get_diff_summary ─────────────────────────────────────────────────


class TestGetDiffSummary:
    @patch("minion.worktree.subprocess.run")
    def test_returns_diff_stat(self, mock_run: MagicMock, wt: Worktree):
        mock_run.return_value = MagicMock(stdout=" file.py | 2 +-\n 1 file changed\n")
        result = wt.get_diff_summary()
        assert "file.py" in result

    @patch("minion.worktree.subprocess.run", side_effect=subprocess.CalledProcessError(1, "git"))
    def test_returns_empty_on_failure(self, mock_run: MagicMock, wt: Worktree):
        assert wt.get_diff_summary() == ""
