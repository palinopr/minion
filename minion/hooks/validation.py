"""Validation hooks -- run linters and checks after agent writes code."""

from __future__ import annotations

import subprocess

from claude_agent_sdk import HookContext, HookInput, HookJSONOutput

from minion.config import ToolsConfig


def create_post_write_linter(tools: ToolsConfig, repo_path: str):
    """Run linter after the agent writes or edits a file."""

    async def lint_after_write(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> HookJSONOutput:
        tool_name = input_data.get("tool_name", "")
        if tool_name not in ("Edit", "Write"):
            return {}

        if not tools.lint_cmd:
            return {}

        try:
            result = subprocess.run(
                tools.lint_cmd.split(),
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                lint_output = (result.stdout + result.stderr).strip()
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": (
                            f"Linter found issues:\n{lint_output}\nPlease fix them."
                        ),
                    }
                }
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return {}

    return lint_after_write
