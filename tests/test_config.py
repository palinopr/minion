"""Tests for minion.config -- load_config and detect_stack."""

from __future__ import annotations

from pathlib import Path

import pytest

from minion.config import (
    GitHubConfig,
    MinionConfig,
    RepoConfig,
    SafetyConfig,
    ToolsConfig,
    detect_stack,
    load_config,
)


# ── load_config ──────────────────────────────────────────────────────


class TestLoadConfigDefaults:
    """When no config file exists, load_config returns defaults."""

    def test_returns_minion_config(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert isinstance(cfg, MinionConfig)

    def test_default_max_parallel(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert cfg.max_parallel == 3

    def test_default_max_rounds(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert cfg.max_rounds == 2

    def test_default_budget(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert cfg.budget_usd == 2.00

    def test_default_repo_config(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert cfg.repo.base_branch == "main"
        assert cfg.repo.branch_prefix == "agent/"

    def test_default_tools_config(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert cfg.tools.lint_cmd == ""
        assert cfg.tools.test_cmd == ""
        assert cfg.tools.format_cmd == ""

    def test_default_github_config(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert cfg.github.create_pr is True
        assert cfg.github.auto_merge is True

    def test_default_safety_config(self, tmp_path: Path):
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert cfg.safety.blocked_commands == []
        assert cfg.safety.protected_files == []


class TestLoadConfigFromFile:
    """load_config reads values from a TOML file."""

    def test_reads_general_section(self, tmp_path: Path):
        toml = tmp_path / "config.toml"
        toml.write_text('[general]\nmax_parallel = 5\nmax_rounds = 10\nbudget_usd = 5.50\n')
        cfg = load_config(toml)
        assert cfg.max_parallel == 5
        assert cfg.max_rounds == 10
        assert cfg.budget_usd == 5.50

    def test_reads_repo_section(self, tmp_path: Path):
        toml = tmp_path / "config.toml"
        toml.write_text('[repo]\npath = "/code"\nbase_branch = "develop"\nbranch_prefix = "bot/"\n')
        cfg = load_config(toml)
        assert cfg.repo.path == "/code"
        assert cfg.repo.base_branch == "develop"
        assert cfg.repo.branch_prefix == "bot/"

    def test_reads_tools_section(self, tmp_path: Path):
        toml = tmp_path / "config.toml"
        toml.write_text('[tools]\nlint_cmd = "eslint ."\ntest_cmd = "jest"\nformat_cmd = "prettier"\n')
        cfg = load_config(toml)
        assert cfg.tools.lint_cmd == "eslint ."
        assert cfg.tools.test_cmd == "jest"
        assert cfg.tools.format_cmd == "prettier"

    def test_reads_github_section(self, tmp_path: Path):
        toml = tmp_path / "config.toml"
        toml.write_text('[github]\ncreate_pr = false\nauto_merge = false\nreviewer = "alice"\n')
        cfg = load_config(toml)
        assert cfg.github.create_pr is False
        assert cfg.github.auto_merge is False
        assert cfg.github.reviewer == "alice"

    def test_reads_safety_section(self, tmp_path: Path):
        toml = tmp_path / "config.toml"
        toml.write_text('[safety]\nblocked_commands = ["rm -rf"]\nprotected_files = [".env"]\n')
        cfg = load_config(toml)
        assert cfg.safety.blocked_commands == ["rm -rf"]
        assert cfg.safety.protected_files == [".env"]

    def test_missing_sections_use_defaults(self, tmp_path: Path):
        toml = tmp_path / "config.toml"
        toml.write_text('[general]\nmax_parallel = 7\n')
        cfg = load_config(toml)
        assert cfg.max_parallel == 7
        assert cfg.tools.test_cmd == ""  # tools section absent → default

    def test_partial_general_section(self, tmp_path: Path):
        toml = tmp_path / "config.toml"
        toml.write_text('[general]\nmax_parallel = 8\n')
        cfg = load_config(toml)
        assert cfg.max_parallel == 8
        assert cfg.max_rounds == 4  # default from load_config fallback, not dataclass default
        assert cfg.budget_usd == 2.00

    def test_empty_toml_file(self, tmp_path: Path):
        toml = tmp_path / "config.toml"
        toml.write_text("")
        cfg = load_config(toml)
        assert cfg.max_parallel == 3  # all defaults

    def test_none_path_uses_default_location(self):
        # When None is passed, it looks for config.toml next to the package.
        # This should not crash even if that file doesn't exist.
        cfg = load_config(None)
        assert isinstance(cfg, MinionConfig)


# ── detect_stack ─────────────────────────────────────────────────────


class TestDetectStackPython:
    """detect_stack recognises Python repos."""

    def test_detects_pyproject_toml(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        tools = detect_stack(tmp_path)
        assert "pytest" in tools.test_cmd

    def test_detects_setup_py(self, tmp_path: Path):
        (tmp_path / "setup.py").write_text("from setuptools import setup\n")
        tools = detect_stack(tmp_path)
        assert "ruff check" in tools.lint_cmd

    def test_python_format_cmd(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").touch()
        tools = detect_stack(tmp_path)
        assert "ruff format" in tools.format_cmd


class TestDetectStackNode:
    """detect_stack recognises Node/TypeScript repos."""

    def test_detects_package_json_with_scripts(self, tmp_path: Path):
        import json
        pkg = {"scripts": {"test": "jest", "lint": "eslint .", "format": "prettier ."}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        tools = detect_stack(tmp_path)
        assert tools.test_cmd == "npm test"
        assert tools.lint_cmd == "npm run lint"
        assert tools.format_cmd == "npm run format"

    def test_package_json_without_scripts(self, tmp_path: Path):
        import json
        (tmp_path / "package.json").write_text(json.dumps({}))
        tools = detect_stack(tmp_path)
        assert tools.test_cmd == ""
        assert tools.lint_cmd == ""

    def test_package_json_partial_scripts(self, tmp_path: Path):
        import json
        pkg = {"scripts": {"test": "vitest"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        tools = detect_stack(tmp_path)
        assert tools.test_cmd == "npm test"
        assert tools.lint_cmd == ""  # no lint script


class TestDetectStackRuby:
    """detect_stack recognises Ruby repos."""

    def test_detects_gemfile(self, tmp_path: Path):
        (tmp_path / "Gemfile").touch()
        tools = detect_stack(tmp_path)
        assert "rspec" in tools.test_cmd
        assert "rubocop" in tools.lint_cmd

    def test_ruby_no_format_cmd(self, tmp_path: Path):
        (tmp_path / "Gemfile").touch()
        tools = detect_stack(tmp_path)
        assert tools.format_cmd == ""


class TestDetectStackGo:
    """detect_stack recognises Go repos."""

    def test_detects_go_mod(self, tmp_path: Path):
        (tmp_path / "go.mod").write_text("module example.com/foo\n")
        tools = detect_stack(tmp_path)
        assert "go test" in tools.test_cmd
        assert "golangci-lint" in tools.lint_cmd


class TestDetectStackEmpty:
    """detect_stack with unknown repos returns empty tools."""

    def test_empty_directory(self, tmp_path: Path):
        tools = detect_stack(tmp_path)
        assert tools.test_cmd == ""
        assert tools.lint_cmd == ""
        assert tools.format_cmd == ""

    def test_returns_tools_config(self, tmp_path: Path):
        tools = detect_stack(tmp_path)
        assert isinstance(tools, ToolsConfig)
