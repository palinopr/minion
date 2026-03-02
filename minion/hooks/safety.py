"""Safety hooks -- block dangerous operations before they execute."""

from __future__ import annotations

import fnmatch

from claude_agent_sdk import HookContext, HookInput, HookJSONOutput

from minion.config import SafetyConfig


def create_command_blocker(safety: SafetyConfig):
    """Block dangerous bash commands."""

    async def block_dangerous_commands(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> HookJSONOutput:
        tool_input = input_data.get("tool_input", {})
        command = tool_input.get("command", "")

        for blocked in safety.blocked_commands:
            if blocked in command:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"Blocked dangerous command: '{blocked}' found in: {command}"
                        ),
                    }
                }
        return {}

    return block_dangerous_commands


def create_file_protector(safety: SafetyConfig):
    """Prevent modification of sensitive files."""

    async def protect_files(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> HookJSONOutput:
        tool_input = input_data.get("tool_input", {})
        file_path = tool_input.get("file_path", "") or tool_input.get("filePath", "")

        if not file_path:
            return {}

        for pattern in safety.protected_files:
            if fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(
                file_path.split("/")[-1], pattern
            ):
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"Protected file: {file_path} matches pattern '{pattern}'"
                        ),
                    }
                }
        return {}

    return protect_files
