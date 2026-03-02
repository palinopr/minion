"""Tests for minion.prefetch -- context prefetching."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from minion.prefetch import (
    PrefetchedContext,
    extract_identifiers,
    extract_paths,
    find_repo_docs,
    find_rules_files,
    format_context_block,
    get_directory_structure,
    grep_repo,
    prefetch_context,
)


# ── extract_paths ────────────────────────────────────────────────────


class TestExtractPaths:
    def test_extracts_python_file(self):
        assert "config.py" in extract_paths("look at config.py for the bug")

    def test_extracts_typescript_file(self):
        paths = extract_paths("the error is in src/App.tsx")
        assert any("App.tsx" in p for p in paths)

    def test_extracts_directory_style_path(self):
        paths = extract_paths("check src/components/Button.tsx")
        assert any("src/components/Button.tsx" in p for p in paths)

    def test_extracts_multiple_paths(self):
        paths = extract_paths("fix auth.py and also look at tests/test_auth.py")
        assert len(paths) >= 2

    def test_deduplicates(self):
        paths = extract_paths("see config.py then again config.py")
        assert paths.count("config.py") == 1

    def test_returns_empty_for_no_paths(self):
        assert extract_paths("fix the authentication bug") == []

    def test_extracts_json_file(self):
        # The regex matches .json extension but greedily captures .js first;
        # "package.json" appears when referenced as a path-like token.
        paths = extract_paths("update the file at src/package.json")
        assert any("package.json" in p for p in paths)

    def test_extracts_toml_file(self):
        paths = extract_paths("edit pyproject.toml")
        assert any("pyproject.toml" in p for p in paths)

    def test_preserves_order(self):
        paths = extract_paths("first alpha.py then beta.py")
        alpha_idx = next(i for i, p in enumerate(paths) if "alpha.py" in p)
        beta_idx = next(i for i, p in enumerate(paths) if "beta.py" in p)
        assert alpha_idx < beta_idx


# ── extract_identifiers ─────────────────────────────────────────────


class TestExtractIdentifiers:
    def test_extracts_camel_case(self):
        ids = extract_identifiers("fix the handleClick function")
        assert "handleClick" in ids

    def test_extracts_pascal_case(self):
        ids = extract_identifiers("the UserProfile component is broken")
        assert "UserProfile" in ids

    def test_extracts_snake_case(self):
        ids = extract_identifiers("update the load_config function")
        assert "load_config" in ids

    def test_filters_stopwords(self):
        ids = extract_identifiers("the error with the code is broken")
        stopwords = {"the", "error", "with", "code", "broken"}
        assert all(i.lower() not in stopwords for i in ids)

    def test_limits_to_15(self):
        # Generate text with many identifiers
        text = " ".join(f"myFunc{i}" for i in range(30))
        ids = extract_identifiers(text)
        assert len(ids) <= 15

    def test_returns_empty_for_plain_text(self):
        # All common short words get filtered
        ids = extract_identifiers("fix the bug")
        assert len(ids) == 0

    def test_deduplicates(self):
        ids = extract_identifiers("handleClick and handleClick again")
        assert ids.count("handleClick") == 1


# ── grep_repo ────────────────────────────────────────────────────────


class TestGrepRepo:
    @patch("minion.prefetch.subprocess.run")
    def test_returns_matching_files(self, mock_run: MagicMock):
        mock_run.return_value = MagicMock(stdout="./src/auth.py\n./src/login.py\n")
        results = grep_repo("/repo", ["authenticate"])
        assert "./src/auth.py" in results

    @patch("minion.prefetch.subprocess.run")
    def test_returns_empty_when_no_matches(self, mock_run: MagicMock):
        mock_run.return_value = MagicMock(stdout="")
        assert grep_repo("/repo", ["nonexistent_xyz"]) == []

    @patch("minion.prefetch.subprocess.run")
    def test_limits_results(self, mock_run: MagicMock):
        files = "\n".join(f"./file{i}.py" for i in range(30))
        mock_run.return_value = MagicMock(stdout=files)
        results = grep_repo("/repo", ["pattern"], max_results=5)
        assert len(results) <= 5

    @patch("minion.prefetch.subprocess.run", side_effect=subprocess.TimeoutExpired("grep", 10))
    def test_handles_timeout(self, mock_run: MagicMock):
        results = grep_repo("/repo", ["slow_pattern"])
        assert results == []

    @patch("minion.prefetch.subprocess.run")
    def test_deduplicates_across_patterns(self, mock_run: MagicMock):
        mock_run.return_value = MagicMock(stdout="./src/auth.py\n")
        results = grep_repo("/repo", ["pat1", "pat2"])
        assert results.count("./src/auth.py") == 1

    @patch("minion.prefetch.subprocess.run")
    def test_limits_patterns_searched(self, mock_run: MagicMock):
        mock_run.return_value = MagicMock(stdout="")
        grep_repo("/repo", [f"p{i}" for i in range(20)])
        assert mock_run.call_count <= 10  # only first 10 patterns


# ── find_rules_files ─────────────────────────────────────────────────


class TestFindRulesFiles:
    def test_finds_root_claude_md(self, tmp_path: Path):
        (tmp_path / "CLAUDE.md").write_text("root rules here")
        rules = find_rules_files(str(tmp_path), [])
        assert len(rules) == 1
        assert "root rules here" in rules[0]

    def test_finds_nested_claude_md(self, tmp_path: Path):
        subdir = tmp_path / "src" / "auth"
        subdir.mkdir(parents=True)
        (subdir / "CLAUDE.md").write_text("auth rules")
        rules = find_rules_files(str(tmp_path), ["src/auth/login.py"])
        assert any("auth rules" in r for r in rules)

    def test_returns_empty_when_no_rules(self, tmp_path: Path):
        assert find_rules_files(str(tmp_path), []) == []

    def test_deduplicates_rules_files(self, tmp_path: Path):
        (tmp_path / "CLAUDE.md").write_text("root")
        rules = find_rules_files(str(tmp_path), ["file1.py", "file2.py"])
        # Root CLAUDE.md should appear only once
        assert len([r for r in rules if "root" in r]) == 1

    def test_truncates_large_rules_files(self, tmp_path: Path):
        (tmp_path / "CLAUDE.md").write_text("x" * 10000)
        rules = find_rules_files(str(tmp_path), [])
        assert len(rules[0]) < 10000


# ── find_repo_docs ───────────────────────────────────────────────────


class TestFindRepoDocs:
    def test_finds_readme(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("# My Project")
        docs = find_repo_docs(str(tmp_path))
        assert any("My Project" in d for d in docs)

    def test_finds_contributing(self, tmp_path: Path):
        (tmp_path / "CONTRIBUTING.md").write_text("how to contribute")
        docs = find_repo_docs(str(tmp_path))
        assert any("contribute" in d for d in docs)

    def test_returns_empty_when_no_docs(self, tmp_path: Path):
        assert find_repo_docs(str(tmp_path)) == []

    def test_truncates_large_docs(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("y" * 10000)
        docs = find_repo_docs(str(tmp_path))
        assert len(docs[0]) < 10000


# ── get_directory_structure ──────────────────────────────────────────


class TestGetDirectoryStructure:
    @patch("minion.prefetch.subprocess.run")
    def test_returns_directory_listing(self, mock_run: MagicMock):
        mock_run.return_value = MagicMock(stdout=".\n./src\n./tests\n")
        result = get_directory_structure("/repo")
        assert "./src" in result

    @patch("minion.prefetch.subprocess.run", side_effect=Exception("find failed"))
    def test_returns_empty_on_failure(self, mock_run: MagicMock):
        assert get_directory_structure("/repo") == ""

    @patch("minion.prefetch.subprocess.run")
    def test_limits_output_lines(self, mock_run: MagicMock):
        dirs = "\n".join(f"./dir{i}" for i in range(100))
        mock_run.return_value = MagicMock(stdout=dirs)
        result = get_directory_structure("/repo")
        assert result.count("\n") <= 49  # max 50 lines


# ── prefetch_context ─────────────────────────────────────────────────


class TestPrefetchContext:
    @patch("minion.prefetch.get_directory_structure", return_value="./src\n./tests")
    @patch("minion.prefetch.grep_repo", return_value=["./src/auth.py"])
    def test_returns_prefetched_context(self, mock_grep, mock_dirs, tmp_path: Path):
        ctx = prefetch_context("fix handleClick in auth.py", str(tmp_path))
        assert isinstance(ctx, PrefetchedContext)

    @patch("minion.prefetch.get_directory_structure", return_value="")
    @patch("minion.prefetch.grep_repo", return_value=[])
    def test_includes_extracted_paths(self, mock_grep, mock_dirs, tmp_path: Path):
        ctx = prefetch_context("fix the bug in config.py", str(tmp_path))
        assert "config.py" in ctx.relevant_files

    @patch("minion.prefetch.get_directory_structure", return_value="./src")
    @patch("minion.prefetch.grep_repo", return_value=[])
    def test_includes_stack_info(self, mock_grep, mock_dirs, tmp_path: Path):
        ctx = prefetch_context("fix stuff", str(tmp_path))
        assert "./src" in ctx.stack_info

    @patch("minion.prefetch.get_directory_structure", return_value="")
    @patch("minion.prefetch.grep_repo", return_value=[])
    def test_loads_docs_for_build_command(self, mock_grep, mock_dirs, tmp_path: Path):
        (tmp_path / "README.md").write_text("# Hello")
        ctx = prefetch_context("build feature", str(tmp_path), command="build")
        assert any("Hello" in d for d in ctx.docs)

    @patch("minion.prefetch.get_directory_structure", return_value="")
    @patch("minion.prefetch.grep_repo", return_value=[])
    def test_skips_docs_for_fix_command(self, mock_grep, mock_dirs, tmp_path: Path):
        (tmp_path / "README.md").write_text("# Hello")
        ctx = prefetch_context("fix bug", str(tmp_path), command="fix")
        assert ctx.docs == []

    @patch("minion.prefetch.get_directory_structure", return_value="")
    @patch("minion.prefetch.grep_repo", return_value=[])
    def test_deduplicates_relevant_files(self, mock_grep, mock_dirs, tmp_path: Path):
        ctx = prefetch_context("look at config.py and config.py", str(tmp_path))
        assert ctx.relevant_files.count("config.py") == 1

    @patch("minion.prefetch.get_directory_structure", return_value="")
    @patch("minion.prefetch.grep_repo", return_value=[])
    def test_limits_relevant_files_to_30(self, mock_grep, mock_dirs, tmp_path: Path):
        many_files = " ".join(f"file{i}.py" for i in range(50))
        ctx = prefetch_context(many_files, str(tmp_path))
        assert len(ctx.relevant_files) <= 30


# ── format_context_block ─────────────────────────────────────────────


class TestFormatContextBlock:
    def test_empty_context_returns_empty_string(self):
        assert format_context_block(PrefetchedContext()) == ""

    def test_includes_relevant_files(self):
        ctx = PrefetchedContext(relevant_files=["auth.py"])
        block = format_context_block(ctx)
        assert "auth.py" in block

    def test_includes_rules(self):
        ctx = PrefetchedContext(rules=["# Root\ndo stuff"])
        block = format_context_block(ctx)
        assert "do stuff" in block

    def test_includes_docs(self):
        ctx = PrefetchedContext(docs=["# README\nhello"])
        block = format_context_block(ctx)
        assert "hello" in block

    def test_wraps_in_prefetch_markers(self):
        ctx = PrefetchedContext(relevant_files=["x.py"])
        block = format_context_block(ctx)
        assert "PREFETCHED CONTEXT" in block
        assert "END PREFETCHED CONTEXT" in block

    def test_limits_files_to_20(self):
        ctx = PrefetchedContext(relevant_files=[f"f{i}.py" for i in range(30)])
        block = format_context_block(ctx)
        assert "f19.py" in block
        assert "f20.py" not in block
