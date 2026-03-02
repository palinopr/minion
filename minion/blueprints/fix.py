"""Fix blueprint -- takes a bug description and produces a fix with tests.

Steps:
  1. [CODE]  Create worktree on new branch
  2. [AGENT] Research: understand the codebase area
  3. [AGENT] Fix: apply minimal change to fix the bug
  4. [CODE]  Lint and format
  5. [CODE]  Run tests
  6. [AGENT] If tests fail, fix them (up to max_rounds)
  7. [CODE]  Commit, push, create PR
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import os

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, ResultMessage, query

from minion.agents.definitions import get_agent_definitions
from minion.blueprints.base import (
    BlueprintResult,
    StepResult,
    StepType,
    format_step_log,
    run_shell,
)
from minion.config import MinionConfig, detect_stack
from minion.hooks.safety import create_command_blocker, create_file_protector
from minion.hooks.validation import create_post_write_linter
from minion.worktree import Worktree


async def run_agent_step(
    prompt: str,
    working_dir: str,
    config: MinionConfig,
    session_id: str | None = None,
) -> tuple[StepResult, str | None]:
    """Run an agent step. Returns (result, session_id)."""
    start = time.time()
    tools_config = detect_stack(Path(working_dir))
    # Merge auto-detected with config overrides
    if config.tools.lint_cmd:
        tools_config.lint_cmd = config.tools.lint_cmd
    if config.tools.test_cmd:
        tools_config.test_cmd = config.tools.test_cmd
    if config.tools.format_cmd:
        tools_config.format_cmd = config.tools.format_cmd

    agents = get_agent_definitions()

    # Load MCP tools from tool shed if any are registered
    from minion.toolshed import load_tools, tools_to_mcp_config
    mcp_tools = load_tools()
    mcp_config = tools_to_mcp_config(mcp_tools) if mcp_tools else {}

    # Send SDK internal noise to /dev/null
    devnull = open(os.devnull, "w")

    opts = ClaudeAgentOptions(
        allowed_tools=["Read", "Edit", "Write", "Bash", "Glob", "Grep", "Task"],
        permission_mode="acceptEdits",
        cwd=working_dir,
        agents=agents,
        max_budget_usd=config.budget_usd,
        debug_stderr=devnull,
        mcp_servers=mcp_config,
        hooks={
            "PreToolUse": [
                HookMatcher(
                    matcher="Bash",
                    hooks=[create_command_blocker(config.safety)],
                ),
                HookMatcher(
                    matcher="Edit|Write",
                    hooks=[create_file_protector(config.safety)],
                ),
            ],
            "PostToolUse": [
                HookMatcher(
                    matcher="Edit|Write",
                    hooks=[create_post_write_linter(tools_config, working_dir)],
                ),
            ],
        },
    )

    if session_id:
        opts.resume = session_id

    captured_session_id = session_id
    final_output = ""

    try:
        async for message in query(prompt=prompt, options=opts):
            if isinstance(message, ResultMessage):
                captured_session_id = message.session_id
                final_output = message.result or ""
    except Exception as e:
        return StepResult(
            success=False,
            output=f"Agent error: {e}",
            duration_seconds=time.time() - start,
        ), captured_session_id

    return StepResult(
        success=True,
        output=final_output[:500] if final_output else "Completed",
        duration_seconds=time.time() - start,
    ), captured_session_id


async def run_fix_blueprint(
    task_description: str,
    repo_path: str,
    task_id: str,
    config: MinionConfig,
) -> BlueprintResult:
    """Execute the fix blueprint end-to-end."""
    result = BlueprintResult(success=False)
    start = time.time()
    repo = Path(repo_path)
    branch = f"{config.repo.branch_prefix}fix-{task_id}"
    result.branch = branch

    # Detect stack
    tools = detect_stack(repo)
    if config.tools.test_cmd:
        tools.test_cmd = config.tools.test_cmd
    if config.tools.lint_cmd:
        tools.lint_cmd = config.tools.lint_cmd
    if config.tools.format_cmd:
        tools.format_cmd = config.tools.format_cmd

    # Step 1 [CODE]: Create worktree
    print(format_step_log(1, StepType.DETERMINISTIC, "Create worktree", StepResult(success=True)))
    wt = Worktree(repo, branch, config.repo.base_branch)
    try:
        wt_path = wt.create()
    except Exception as e:
        print(f"  Failed to create worktree: {e}")
        result.steps.append(StepResult(success=False, output=str(e)))
        return result
    working_dir = str(wt_path)

    try:
        # Step 2 [AGENT]: Research and fix
        print(format_step_log(2, StepType.AGENT, "Analyze and fix", StepResult(success=True, duration_seconds=0)))
        agent_prompt = (
            f"Task: {task_description}\n\n"
            "Instructions:\n"
            "1. First, explore the codebase to understand the relevant code\n"
            "2. Find the root cause of the issue\n"
            "3. Apply the minimal fix\n"
            "4. Write or update tests to cover the fix\n"
            "5. Make sure your changes are complete and correct"
        )
        step2, session_id = await run_agent_step(agent_prompt, working_dir, config)
        result.steps.append(step2)
        result.session_id = session_id
        print(format_step_log(2, StepType.AGENT, "Analyze and fix", step2))

        if not step2.success:
            return result

        # Step 3 [CODE]: Lint and format
        if tools.lint_cmd:
            lint_result = run_shell(tools.lint_cmd, working_dir)
            result.steps.append(lint_result)
            print(format_step_log(3, StepType.DETERMINISTIC, "Lint", lint_result))

        if tools.format_cmd:
            fmt_result = run_shell(tools.format_cmd, working_dir)
            result.steps.append(fmt_result)
            print(format_step_log(3, StepType.DETERMINISTIC, "Format", fmt_result))

        # Step 4 [CODE]: Run tests + feedback loop
        if tools.test_cmd:
            for round_num in range(config.max_rounds):
                test_result = run_shell(tools.test_cmd, working_dir, timeout=300)
                result.steps.append(test_result)
                print(format_step_log(
                    4, StepType.DETERMINISTIC,
                    f"Tests (round {round_num + 1}/{config.max_rounds})",
                    test_result,
                ))

                if test_result.success:
                    break

                if round_num < config.max_rounds - 1:
                    # [AGENT]: Fix test failures
                    fix_prompt = (
                        f"Tests failed. Here is the output:\n\n"
                        f"{test_result.output[:2000]}\n\n"
                        "Fix the failing tests. Do not skip or delete tests."
                    )
                    fix_step, session_id = await run_agent_step(
                        fix_prompt, working_dir, config, session_id,
                    )
                    result.steps.append(fix_step)
                    result.session_id = session_id
                    print(format_step_log(
                        4, StepType.AGENT,
                        f"Fix tests (round {round_num + 1})",
                        fix_step,
                    ))

                    # Re-lint after agent fix
                    if tools.lint_cmd:
                        run_shell(tools.lint_cmd, working_dir)

        # Step 5 [CODE]: Commit, push, PR
        committed = wt.commit_and_push(f"fix: {task_description[:72]}")
        if committed:
            print(format_step_log(5, StepType.DETERMINISTIC, "Commit and push", StepResult(success=True)))

            if config.github.create_pr:
                pr_url = wt.create_pr(
                    title=f"fix: {task_description[:72]}",
                    body=(
                        f"## Agent-generated fix\n\n"
                        f"**Task:** {task_description}\n\n"
                        f"**Rounds:** {len(result.steps)}\n\n"
                        f"Generated by minion on branch `{branch}`"
                    ),
                    reviewer=config.github.reviewer,
                )
                result.pr_url = pr_url
                if pr_url:
                    print(f"  PR: {pr_url}")
        else:
            print("  No changes to commit")

        result.success = True

    finally:
        result.total_duration = time.time() - start
        # Don't clean up worktree on success -- keep it for review
        if not result.success:
            wt.cleanup()

    return result
