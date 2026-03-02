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

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

from minion.blueprints.base import BlueprintResult, StepResult, StepType, format_step_log
from minion.config import MinionConfig
from minion.prefetch import format_context_block, prefetch_context


async def run_review_blueprint(
    target: str,
    repo_path: str,
    config: MinionConfig,
) -> BlueprintResult:
    """Review code. Target can be a file path, directory, or PR number."""
    result = BlueprintResult(success=False)
    start = time.time()

    # Step 1 [CODE]: Prefetch context
    ctx = prefetch_context(target, repo_path, command="review")
    context_block = format_context_block(ctx)
    prefetch_info = f"{len(ctx.relevant_files)} files, {len(ctx.rules)} rules"
    print(format_step_log(1, StepType.DETERMINISTIC, f"Prefetch context ({prefetch_info})", StepResult(success=True)))

    prompt = (
        f"{context_block}"
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

    text_chunks: list[str] = []
    final_output = ""
    try:
        async for message in query(prompt=prompt, options=opts):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text:
                        text_chunks.append(block.text)
            elif isinstance(message, ResultMessage):
                final_output = message.result or ""
                result.total_cost_usd = message.total_cost_usd or 0.0
    except Exception as e:
        result.steps.append(StepResult(success=False, output=str(e)))
        result.total_duration = time.time() - start
        return result

    # Use whichever source captured more content
    collected = "\n\n".join(text_chunks)
    review_text = collected if len(collected) > len(final_output) else final_output
    step = StepResult(success=True, output=review_text, duration_seconds=time.time() - start)
    result.steps.append(step)
    result.success = True
    result.total_duration = time.time() - start

    print(format_step_log(2, StepType.AGENT, "Code review", step))
    if review_text:
        print(f"\n{review_text}")

    return result
