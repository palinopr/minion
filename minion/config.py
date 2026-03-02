"""Load and validate minion configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SafetyConfig:
    blocked_commands: list[str] = field(default_factory=list)
    protected_files: list[str] = field(default_factory=list)


@dataclass
class RepoConfig:
    path: str = ""
    base_branch: str = "main"
    branch_prefix: str = "agent/"


@dataclass
class ToolsConfig:
    lint_cmd: str = ""
    test_cmd: str = ""
    format_cmd: str = ""


@dataclass
class GitHubConfig:
    create_pr: bool = True
    reviewer: str = ""


@dataclass
class MinionConfig:
    max_parallel: int = 3
    max_rounds: int = 2
    budget_usd: float = 2.00
    repo: RepoConfig = field(default_factory=RepoConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)


def load_config(config_path: Path | None = None) -> MinionConfig:
    """Load config from TOML file, falling back to defaults."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.toml"

    if not config_path.exists():
        return MinionConfig()

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    general = raw.get("general", {})
    return MinionConfig(
        max_parallel=general.get("max_parallel", 3),
        max_rounds=general.get("max_rounds", 4),
        budget_usd=general.get("budget_usd", 2.00),
        repo=RepoConfig(**raw.get("repo", {})),
        tools=ToolsConfig(**raw.get("tools", {})),
        github=GitHubConfig(**raw.get("github", {})),
        safety=SafetyConfig(**raw.get("safety", {})),
    )


def detect_stack(repo_path: Path) -> ToolsConfig:
    """Auto-detect lint/test/format commands from repo contents."""
    tools = ToolsConfig()

    # Python
    if (repo_path / "pyproject.toml").exists() or (repo_path / "setup.py").exists():
        tools.test_cmd = tools.test_cmd or "pytest --tb=short -q"
        tools.lint_cmd = tools.lint_cmd or "ruff check --fix ."
        tools.format_cmd = tools.format_cmd or "ruff format ."
        return tools

    # Node/TypeScript
    pkg_json = repo_path / "package.json"
    if pkg_json.exists():
        import json
        with open(pkg_json) as f:
            pkg = json.load(f)
        scripts = pkg.get("scripts", {})
        tools.test_cmd = tools.test_cmd or (f"npm test" if "test" in scripts else "")
        tools.lint_cmd = tools.lint_cmd or (f"npm run lint" if "lint" in scripts else "")
        tools.format_cmd = tools.format_cmd or (f"npm run format" if "format" in scripts else "")
        return tools

    # Ruby
    if (repo_path / "Gemfile").exists():
        tools.test_cmd = tools.test_cmd or "bundle exec rspec"
        tools.lint_cmd = tools.lint_cmd or "bundle exec rubocop -a"
        return tools

    # Go
    if (repo_path / "go.mod").exists():
        tools.test_cmd = tools.test_cmd or "go test ./..."
        tools.lint_cmd = tools.lint_cmd or "golangci-lint run"
        return tools

    return tools
