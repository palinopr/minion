"""Tool shed -- a registry of MCP servers your agents can discover and use.

This is Stripe's "tool shed" concept: instead of loading all 500 tools
into every agent's context, the agent asks the tool shed what's available
and only loads what it needs.

To add a tool:
    1. Add it to tools.toml
    2. The agent will discover it automatically via the tool shed MCP server

Example tools.toml:
    [[tools]]
    name = "github"
    description = "GitHub API: issues, PRs, reviews, actions"
    command = "npx"
    args = ["@modelcontextprotocol/server-github"]
    env = {GITHUB_TOKEN = "${GITHUB_TOKEN}"}
    tags = ["vcs", "issues", "prs"]

    [[tools]]
    name = "postgres"
    description = "Query PostgreSQL databases"
    command = "npx"
    args = ["@modelcontextprotocol/server-postgres"]
    env = {DATABASE_URL = "${DATABASE_URL}"}
    tags = ["database", "sql"]
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ToolEntry:
    name: str
    description: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


def load_tools(tools_path: Path | None = None) -> list[ToolEntry]:
    """Load tool definitions from tools.toml."""
    if tools_path is None:
        tools_path = Path(__file__).parent.parent / "tools.toml"

    if not tools_path.exists():
        return []

    with open(tools_path, "rb") as f:
        raw = tomllib.load(f)

    entries = []
    for t in raw.get("tools", []):
        # Expand environment variables in env values
        env = {}
        for k, v in t.get("env", {}).items():
            if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                var_name = v[2:-1]
                env[k] = os.environ.get(var_name, "")
            else:
                env[k] = v

        entries.append(ToolEntry(
            name=t["name"],
            description=t.get("description", ""),
            command=t["command"],
            args=t.get("args", []),
            env=env,
            tags=t.get("tags", []),
        ))
    return entries


def find_tools(query: str, tools: list[ToolEntry]) -> list[ToolEntry]:
    """Find tools matching a query by name, description, or tags."""
    query_lower = query.lower()
    results = []
    for tool in tools:
        searchable = f"{tool.name} {tool.description} {' '.join(tool.tags)}".lower()
        if query_lower in searchable:
            results.append(tool)
    return results


def tools_to_mcp_config(tools: list[ToolEntry]) -> dict:
    """Convert tool entries to ClaudeAgentOptions mcp_servers format."""
    config = {}
    for tool in tools:
        entry = {"command": tool.command, "args": tool.args}
        if tool.env:
            entry["env"] = tool.env
        config[tool.name] = entry
    return config


def format_tool_list(tools: list[ToolEntry]) -> str:
    """Format tools for display."""
    if not tools:
        return "No tools registered. Add them to tools.toml"

    lines = [
        f"{'Name':<20} {'Tags':<25} {'Description':<40}",
        "-" * 85,
    ]
    for t in tools:
        tags = ", ".join(t.tags) if t.tags else "-"
        lines.append(f"{t.name:<20} {tags:<25} {t.description[:40]:<40}")
    return "\n".join(lines)
