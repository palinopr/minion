"""Build blueprint -- implements a new feature from a spec.

Steps:
  1. [CODE]  Create worktree on new branch
  2. [AGENT] Research: understand architecture and conventions
  3. [AGENT] Implement: write the feature code
  4. [AGENT] Test: write tests for the new code
  5. [CODE]  Lint and format
  6. [CODE]  Run tests
  7. [AGENT] Fix failures (up to max_rounds)
  8. [CODE]  Commit, push, create PR
"""

from __future__ import annotations

import time
from pathlib import Path

from minion.blueprints.base import (
    BlueprintResult,
    StepResult,
    StepType,
    format_step_log,
    run_shell,
)
from minion.blueprints.fix import run_agent_step
from minion.config import MinionConfig, detect_stack
from minion.prefetch import format_context_block, prefetch_context
from minion.worktree import Worktree


async def run_build_blueprint(
    feature_spec: str,
    repo_path: str,
    task_id: str,
    config: MinionConfig,
) -> BlueprintResult:
    """Execute the build blueprint for a new feature."""
    result = BlueprintResult(success=False)
    start = time.time()
    repo = Path(repo_path)
    branch = f"{config.repo.branch_prefix}feat-{task_id}"
    result.branch = branch

    tools = detect_stack(repo)
    if config.tools.test_cmd:
        tools.test_cmd = config.tools.test_cmd
    if config.tools.lint_cmd:
        tools.lint_cmd = config.tools.lint_cmd
    if config.tools.format_cmd:
        tools.format_cmd = config.tools.format_cmd

    # Step 1 [CODE]: Create worktree
    wt = Worktree(repo, branch, config.repo.base_branch)
    try:
        wt_path = wt.create()
    except Exception as e:
        result.steps.append(StepResult(success=False, output=str(e)))
        return result
    working_dir = str(wt_path)

    try:
        # Step 2 [CODE]: Prefetch context
        ctx = prefetch_context(feature_spec, repo_path, command="build")
        context_block = format_context_block(ctx)
        prefetch_info = f"{len(ctx.relevant_files)} files, {len(ctx.rules)} rules"
        print(format_step_log(2, StepType.DETERMINISTIC, f"Prefetch context ({prefetch_info})", StepResult(success=True)))

        # Step 3 [AGENT]: Research architecture
        research_prompt = (
            f"{context_block}"
            "Before implementing anything, explore this codebase:\n"
            "1. Understand the directory structure and architecture\n"
            "2. Find similar features to understand the pattern\n"
            "3. Identify where new code should go\n"
            "4. Note naming conventions, imports, and patterns\n"
            "5. Summarize your findings before proceeding\n\n"
            f"The feature to implement:\n{feature_spec}"
        )
        step, session_id = await run_agent_step(research_prompt, working_dir, config)
        result.steps.append(step)
        result.session_id = session_id
        print(format_step_log(3, StepType.AGENT, "Research", step))

        # Step 4 [AGENT]: Implement the feature
        impl_prompt = (
            "Now implement the feature based on your research.\n"
            "- Follow the existing architecture and patterns you found\n"
            "- Keep functions under 50 lines\n"
            "- Add type hints to all functions\n"
            "- Write tests alongside the implementation\n"
            "- Make sure imports and references are correct"
        )
        step, session_id = await run_agent_step(impl_prompt, working_dir, config, session_id)
        result.steps.append(step)
        print(format_step_log(4, StepType.AGENT, "Implement", step))

        # Step 5 [CODE]: Lint and format
        if tools.lint_cmd:
            lint_result = run_shell(tools.lint_cmd, working_dir)
            result.steps.append(lint_result)
            print(format_step_log(5, StepType.DETERMINISTIC, "Lint", lint_result))

        if tools.format_cmd:
            fmt_result = run_shell(tools.format_cmd, working_dir)
            result.steps.append(fmt_result)
            print(format_step_log(5, StepType.DETERMINISTIC, "Format", fmt_result))

        # Step 6 [CODE]: Run tests + feedback loop
        if tools.test_cmd:
            for round_num in range(config.max_rounds):
                test_result = run_shell(tools.test_cmd, working_dir, timeout=300)
                result.steps.append(test_result)
                print(format_step_log(6, StepType.DETERMINISTIC, f"Tests (round {round_num + 1})", test_result))

                if test_result.success:
                    break

                if round_num < config.max_rounds - 1:
                    fix_prompt = (
                        f"Tests failed:\n\n{test_result.output[:2000]}\n\n"
                        "Fix the failures. Do not delete or skip tests."
                    )
                    fix_step, session_id = await run_agent_step(
                        fix_prompt, working_dir, config, session_id,
                    )
                    result.steps.append(fix_step)
                    print(format_step_log(6, StepType.AGENT, f"Fix (round {round_num + 1})", fix_step))

                    if tools.lint_cmd:
                        run_shell(tools.lint_cmd, working_dir)

        # Step 7 [CODE]: Commit, push, PR
        committed = wt.commit_and_push(f"feat: {feature_spec[:72]}")
        if committed and config.github.create_pr:
            pr_url = wt.create_pr(
                title=f"feat: {feature_spec[:72]}",
                body=(
                    f"## Agent-generated feature\n\n"
                    f"**Spec:** {feature_spec}\n\n"
                    f"Generated by minion on branch `{branch}`"
                ),
                reviewer=config.github.reviewer,
            )
            result.pr_url = pr_url
            if pr_url:
                print(f"  PR: {pr_url}")

        result.success = True

    finally:
        result.total_duration = time.time() - start
        if not result.success:
            wt.cleanup()

    return result
