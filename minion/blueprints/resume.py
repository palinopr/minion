"""Resume blueprint -- continue a failed or incomplete run.

Loads the session ID from a previous run's history and gives the agent
additional instructions to finish the job.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from minion.blueprints.base import BlueprintResult, StepResult, StepType, format_step_log
from minion.blueprints.fix import run_agent_step
from minion.config import MinionConfig, detect_stack
from minion.history import HISTORY_DIR
from minion.worktree import Worktree


def find_run(task_id: str) -> dict | None:
    """Find a run by task ID prefix."""
    if not HISTORY_DIR.exists():
        return None

    for f in sorted(HISTORY_DIR.glob("*.json"), reverse=True):
        with open(f) as fh:
            run = json.load(fh)
        if run.get("task_id", "").startswith(task_id):
            return run
    return None


async def run_resume_blueprint(
    task_id: str,
    instructions: str,
    config: MinionConfig,
) -> BlueprintResult:
    """Resume a previous run with additional instructions."""
    result = BlueprintResult(success=False)
    start = time.time()

    run = find_run(task_id)
    if not run:
        print(f"  No run found matching task ID: {task_id}")
        return result

    session_id = run.get("session_id")
    repo_path = run.get("repo_path", "")
    branch = run.get("branch", "")

    if not session_id:
        print(f"  Run {task_id} has no session ID -- cannot resume.")
        return result

    print(f"  Resuming: {run.get('description', '')[:60]}")
    print(f"  Branch:   {branch}")
    print(f"  Session:  {session_id[:16]}...")

    # Find the worktree if it still exists
    repo = Path(repo_path)
    wt = Worktree(repo, branch, config.repo.base_branch)
    if wt.worktree_path.exists():
        working_dir = str(wt.worktree_path)
    else:
        # Worktree was cleaned up -- recreate from branch if it exists
        print(f"  Worktree gone. Creating fresh from branch {branch}...")
        try:
            wt_path = wt.create()
            working_dir = str(wt_path)
        except Exception as e:
            print(f"  Could not recreate worktree: {e}")
            return result

    prompt = (
        f"You are continuing a previous task that was interrupted or failed.\n"
        f"Previous task: {run.get('description', '')}\n\n"
        f"Additional instructions:\n{instructions}\n\n"
        f"Pick up where you left off. Check the current state of the code "
        f"and complete the task."
    )

    step, new_session = await run_agent_step(prompt, working_dir, config, session_id)
    result.steps.append(step)
    result.session_id = new_session
    result.branch = branch
    print(format_step_log(1, StepType.AGENT, "Resume", step))

    # Run tests if available
    tools = detect_stack(repo)
    if config.tools.test_cmd:
        tools.test_cmd = config.tools.test_cmd

    if tools.test_cmd:
        from minion.blueprints.base import run_shell
        test_result = run_shell(tools.test_cmd, working_dir, timeout=300)
        result.steps.append(test_result)
        print(format_step_log(2, StepType.DETERMINISTIC, "Tests", test_result))

    # Commit if there are changes
    committed = wt.commit_and_push(f"fix: resume {run.get('description', '')[:60]}")
    if committed:
        print(format_step_log(3, StepType.DETERMINISTIC, "Commit", StepResult(success=True)))

    result.success = step.success
    result.total_duration = time.time() - start
    return result
