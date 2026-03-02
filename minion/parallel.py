"""Parallel runner -- spin up multiple minions at once on your Mac Mini.

Uses asyncio.gather to run up to max_parallel agents concurrently.
Each agent gets its own git worktree, so they don't interfere.

With 10 cores and 16GB RAM, you can comfortably run 3 agents in parallel.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from minion.blueprints.base import BlueprintResult
from minion.config import MinionConfig


@dataclass
class ParallelTask:
    command: str  # fix, test, review, build
    description: str
    repo_path: str
    task_id: str


@dataclass
class ParallelResult:
    task: ParallelTask
    result: BlueprintResult
    error: str | None = None


async def run_single(task: ParallelTask, config: MinionConfig) -> ParallelResult:
    """Run a single task, catching errors so other tasks aren't affected."""
    try:
        if task.command == "fix":
            from minion.blueprints.fix import run_fix_blueprint
            result = await run_fix_blueprint(task.description, task.repo_path, task.task_id, config)
        elif task.command == "test":
            from minion.blueprints.test import run_test_blueprint
            result = await run_test_blueprint(task.description, task.repo_path, task.task_id, config)
        elif task.command == "review":
            from minion.blueprints.review import run_review_blueprint
            result = await run_review_blueprint(task.description, task.repo_path, config)
        elif task.command == "build":
            from minion.blueprints.build import run_build_blueprint
            result = await run_build_blueprint(task.description, task.repo_path, task.task_id, config)
        else:
            return ParallelResult(
                task=task,
                result=BlueprintResult(success=False),
                error=f"Unknown command: {task.command}",
            )
        return ParallelResult(task=task, result=result)
    except Exception as e:
        return ParallelResult(
            task=task,
            result=BlueprintResult(success=False),
            error=str(e),
        )


async def run_parallel(
    tasks: list[ParallelTask],
    config: MinionConfig,
) -> list[ParallelResult]:
    """Run multiple tasks in parallel, respecting max_parallel limit.

    Uses a semaphore to cap concurrency at config.max_parallel.
    """
    semaphore = asyncio.Semaphore(config.max_parallel)

    async def throttled(task: ParallelTask) -> ParallelResult:
        async with semaphore:
            print(f"  Starting: [{task.command}] {task.description[:50]}")
            result = await run_single(task, config)
            status = "OK" if result.result.success else "FAIL"
            print(f"  Finished: [{task.command}] {task.description[:50]} -> {status}")
            return result

    results = await asyncio.gather(*[throttled(t) for t in tasks])
    return list(results)


def format_parallel_results(results: list[ParallelResult]) -> str:
    """Format parallel run results as a summary table."""
    lines = [
        f"{'Cmd':<7} {'OK?':<5} {'Duration':<10} {'Description':<45} {'PR':<10}",
        "-" * 80,
    ]
    for r in results:
        ok = "yes" if r.result.success else "FAIL"
        dur = f"{r.result.total_duration:.0f}s"
        desc = r.task.description[:45]
        pr = r.result.pr_url or ""
        pr = pr[-30:] if len(pr) > 30 else pr
        if r.error:
            desc = f"{desc} (error: {r.error[:20]})"
        lines.append(f"{r.task.command:<7} {ok:<5} {dur:<10} {desc:<45} {pr:<10}")

    total = len(results)
    passed = sum(1 for r in results if r.result.success)
    lines.append(f"\n{passed}/{total} succeeded")
    return "\n".join(lines)
