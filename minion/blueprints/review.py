"""Review blueprint -- reviews code and returns findings. No worktree needed.

Steps:
  1. [AGENT] Analyze the target code
  2. [AGENT] Check for bugs, security, performance, style
  3. Return structured findings (no commits, no PRs)
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from minion.blueprints.base import BlueprintResult, StepResult, StepType, format_step_log
from minion.config import MinionConfig


async def run_review_blueprint(
    target: str,
    repo_path: str,
    config: MinionConfig,
) -> BlueprintResult:
    """Review code. Target can be a file path, directory, or PR number."""
    result = BlueprintResult(success=False)
    start = time.time()

    prompt = (
        f"Review target: {target}\n\n"
        "Perform a thorough code review. Check for:\n"
        "1. Bugs and logic errors\n"
        "2. Security vulnerabilities (injection, auth bypass, data exposure)\n"
        "3. Missing error handling\n"
        "4. Performance problems (N+1 queries, unbounded loops, memory leaks)\n"
        "5. Race conditions or concurrency issues\n"
        "6. Missing input validation\n\n"
        "Format your findings as:\n"
        "- CRITICAL: [file:line] description\n"
        "- WARNING: [file:line] description\n"
        "- INFO: [file:line] description\n\n"
        "If you find no issues, say so. Do not invent problems."
    )

    devnull = open(os.devnull, "w")
    opts = ClaudeAgentOptions(
        allowed_tools=["Read", "Glob", "Grep", "Bash"],
        permission_mode="plan",  # read-only
        cwd=repo_path,
        max_budget_usd=config.budget_usd,
        debug_stderr=devnull,
    )

    final_output = ""
    try:
        async for message in query(prompt=prompt, options=opts):
            if isinstance(message, ResultMessage):
                final_output = message.result or ""
    except Exception as e:
        result.steps.append(StepResult(success=False, output=str(e)))
        result.total_duration = time.time() - start
        return result

    step = StepResult(success=True, output=final_output or "", duration_seconds=time.time() - start)
    result.steps.append(step)
    result.success = True
    result.total_duration = time.time() - start

    print(format_step_log(1, StepType.AGENT, "Code review", step))
    if final_output:
        print(f"\n{final_output}")

    return result
