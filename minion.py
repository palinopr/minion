#!/usr/bin/env python3
"""Minion CLI -- unattended coding agents on your Mac Mini.

Usage:
    minion fix   --repo ~/myapp "login crashes on empty email"
    minion test  --repo ~/myapp "src/auth/"
    minion review --repo ~/myapp "src/payments/checkout.py"
    minion build --repo ~/myapp "Add rate limiting to /api/search"
    minion batch --repo ~/myapp tasks.txt
    minion status
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from minion.config import MinionConfig, load_config
from minion.quiet import install_stderr_filter


def check_api_key() -> None:
    """Fail fast if no auth method is available."""
    # Direct API key
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    # Cloud provider flags
    if any(os.environ.get(v) for v in [
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
    ]):
        return
    # Claude CLI is authenticated (SDK uses it under the hood)
    import shutil
    if shutil.which("claude"):
        return

    print("Error: No authentication found.")
    print("  Option 1: export ANTHROPIC_API_KEY=sk-ant-...")
    print("  Option 2: Install and auth Claude CLI (claude login)")
    print("  Option 3: Set CLAUDE_CODE_USE_BEDROCK=1 / CLAUDE_CODE_USE_VERTEX=1")
    sys.exit(1)


def make_task_id(description: str) -> str:
    """Short deterministic ID from the task description + timestamp."""
    h = hashlib.sha256(f"{description}{time.time()}".encode()).hexdigest()[:8]
    return h


def resolve_repo(args_repo: str | None, config: MinionConfig) -> str:
    """Get the repo path from args or config, validate it exists."""
    repo = args_repo or config.repo.path
    if not repo:
        print("Error: No repo specified. Use --repo or set repo.path in config.toml")
        sys.exit(1)

    repo_path = Path(repo).expanduser().resolve()
    if not repo_path.exists():
        print(f"Error: Repo path does not exist: {repo_path}")
        sys.exit(1)

    if not (repo_path / ".git").exists():
        print(f"Error: Not a git repository: {repo_path}")
        sys.exit(1)

    return str(repo_path)


def print_header(command: str, description: str, repo: str, task_id: str, config: MinionConfig) -> None:
    """Print consistent run header."""
    print(f"Minion {command}: {description}")
    print(f"  Repo:       {repo}")
    print(f"  Task:       {task_id}")
    print(f"  Max rounds: {config.max_rounds}")
    print(f"  Budget:     ${config.budget_usd:.2f}")
    print()


async def cmd_fix(args: argparse.Namespace, config: MinionConfig) -> None:
    """Fix a bug."""
    from minion.blueprints.fix import run_fix_blueprint
    from minion.history import save_run

    repo = resolve_repo(args.repo, config)
    task_id = make_task_id(args.description)
    print_header("fix", args.description, repo, task_id, config)

    result = await run_fix_blueprint(args.description, repo, task_id, config)
    save_run("fix", args.description, repo, task_id, result)

    print()
    if result.success:
        print(f"Done in {result.total_duration:.1f}s")
        if result.pr_url:
            print(f"PR: {result.pr_url}")
    else:
        print(f"Failed after {result.total_duration:.1f}s")
        sys.exit(1)


async def cmd_test(args: argparse.Namespace, config: MinionConfig) -> None:
    """Add test coverage."""
    from minion.blueprints.test import run_test_blueprint
    from minion.history import save_run

    repo = resolve_repo(args.repo, config)
    task_id = make_task_id(args.target)
    print_header("test", args.target, repo, task_id, config)

    result = await run_test_blueprint(args.target, repo, task_id, config)
    save_run("test", args.target, repo, task_id, result)

    print()
    if result.success:
        print(f"Done in {result.total_duration:.1f}s")
        if result.pr_url:
            print(f"PR: {result.pr_url}")
    else:
        print(f"Failed after {result.total_duration:.1f}s")
        sys.exit(1)


async def cmd_review(args: argparse.Namespace, config: MinionConfig) -> None:
    """Review code (read-only)."""
    from minion.blueprints.review import run_review_blueprint
    from minion.history import save_run

    repo = resolve_repo(args.repo, config)
    print(f"Minion review: {args.target}")
    print(f"  Repo: {repo}")
    print()

    result = await run_review_blueprint(args.target, repo, config)
    save_run("review", args.target, repo, "review", result)

    print()
    if result.success:
        print(f"Review complete in {result.total_duration:.1f}s")
    else:
        print(f"Review failed after {result.total_duration:.1f}s")
        sys.exit(1)


async def cmd_build(args: argparse.Namespace, config: MinionConfig) -> None:
    """Build a new feature."""
    from minion.blueprints.build import run_build_blueprint
    from minion.history import save_run

    repo = resolve_repo(args.repo, config)
    task_id = make_task_id(args.spec)
    print_header("build", args.spec, repo, task_id, config)

    result = await run_build_blueprint(args.spec, repo, task_id, config)
    save_run("build", args.spec, repo, task_id, result)

    print()
    if result.success:
        print(f"Done in {result.total_duration:.1f}s")
        if result.pr_url:
            print(f"PR: {result.pr_url}")
    else:
        print(f"Failed after {result.total_duration:.1f}s")
        sys.exit(1)


async def cmd_resume(args: argparse.Namespace, config: MinionConfig) -> None:
    """Resume a previous failed or incomplete run."""
    from minion.blueprints.resume import run_resume_blueprint
    from minion.history import save_run

    print(f"Minion resume: {args.task_id}")
    print(f"  Instructions: {args.instructions}")
    print()

    result = await run_resume_blueprint(args.task_id, args.instructions, config)
    save_run("resume", args.instructions, "", args.task_id, result)

    print()
    if result.success:
        print(f"Done in {result.total_duration:.1f}s")
    else:
        print(f"Failed after {result.total_duration:.1f}s")
        sys.exit(1)


async def cmd_batch(args: argparse.Namespace, config: MinionConfig) -> None:
    """Run multiple tasks in parallel from a file.

    File format (one task per line):
        fix: login crashes on empty email
        test: src/auth/
        review: src/payments/checkout.py
        build: Add rate limiting
    """
    from minion.history import save_run
    from minion.parallel import ParallelTask, format_parallel_results, run_parallel

    repo = resolve_repo(args.repo, config)
    task_file = Path(args.file)

    if not task_file.exists():
        print(f"Error: Task file not found: {task_file}")
        sys.exit(1)

    tasks = []
    with open(task_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                print(f"Skipping malformed line (expected 'command: description'): {line}")
                continue
            cmd, desc = line.split(":", 1)
            cmd = cmd.strip().lower()
            desc = desc.strip()
            if cmd not in ("fix", "test", "review", "build"):
                print(f"Skipping unknown command: {cmd}")
                continue
            tasks.append(ParallelTask(
                command=cmd,
                description=desc,
                repo_path=repo,
                task_id=make_task_id(desc),
            ))

    if not tasks:
        print("No valid tasks found in file.")
        sys.exit(1)

    print(f"Minion batch: {len(tasks)} tasks, max {config.max_parallel} parallel")
    print(f"  Repo: {repo}")
    print()

    results = await run_parallel(tasks, config)

    for r in results:
        save_run(r.task.command, r.task.description, repo, r.task.task_id, r.result)

    print()
    print(format_parallel_results(results))

    failed = sum(1 for r in results if not r.result.success)
    if failed:
        sys.exit(1)


def cmd_status(args: argparse.Namespace, config: MinionConfig) -> None:
    """Show recent runs."""
    from minion.history import format_run_table, list_runs

    limit = getattr(args, "limit", 20)
    runs = list_runs(limit=limit)
    print(format_run_table(runs))


def cmd_tools(args: argparse.Namespace, config: MinionConfig) -> None:
    """List registered MCP tools."""
    from minion.toolshed import format_tool_list, load_tools

    tools = load_tools()
    print(format_tool_list(tools))


def cmd_dashboard(args: argparse.Namespace, config: MinionConfig) -> None:
    """Launch the web dashboard."""
    from minion.dashboard.app import run_dashboard

    port = getattr(args, "port", 7777)
    run_dashboard(port=port)


def cmd_clean(args: argparse.Namespace, config: MinionConfig) -> None:
    """Clean up leftover worktrees from failed runs."""
    repo = resolve_repo(args.repo, config)
    repo_path = Path(repo)
    worktree_dir = repo_path.parent / ".worktrees"

    if not worktree_dir.exists():
        print("No worktrees to clean.")
        return

    import subprocess
    # List existing git worktrees
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    worktrees = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree ") and ".worktrees/" in line:
            worktrees.append(line.split("worktree ", 1)[1])

    if not worktrees:
        print("No agent worktrees found.")
        return

    print(f"Found {len(worktrees)} agent worktree(s):")
    for wt in worktrees:
        print(f"  {wt}")

    if not args.force:
        print("\nRun with --force to remove them.")
        return

    for wt in worktrees:
        subprocess.run(
            ["git", "worktree", "remove", wt, "--force"],
            cwd=repo,
            capture_output=True,
        )
        print(f"  Removed: {wt}")

    # Prune
    subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)
    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="minion",
        description="Unattended coding agents on your Mac Mini",
    )
    parser.add_argument("--config", type=str, default=None, help="Path to config.toml")
    parser.add_argument("--repo", type=str, default=None, help="Path to git repository")

    # Shared flags for subparsers so --repo works before or after the command
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--repo", type=str, default=None, help="Path to git repository")
    shared.add_argument("--config", type=str, default=None, help="Path to config.toml")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # fix
    p = subparsers.add_parser("fix", help="Fix a bug", parents=[shared])
    p.add_argument("description", help="Description of the bug to fix")

    # test
    p = subparsers.add_parser("test", help="Add test coverage", parents=[shared])
    p.add_argument("target", help="File, directory, or description to test")

    # review
    p = subparsers.add_parser("review", help="Review code (read-only)", parents=[shared])
    p.add_argument("target", help="File, directory, or PR to review")

    # build
    p = subparsers.add_parser("build", help="Build a new feature", parents=[shared])
    p.add_argument("spec", help="Feature specification")

    # resume
    p = subparsers.add_parser("resume", help="Continue a failed run")
    p.add_argument("task_id", help="Task ID from a previous run (from 'minion status')")
    p.add_argument("instructions", nargs="?", default="Continue and finish the task.", help="Additional instructions")

    # batch
    p = subparsers.add_parser("batch", help="Run multiple tasks from a file", parents=[shared])
    p.add_argument("file", help="Path to task file (one per line: 'command: description')")

    # status
    p = subparsers.add_parser("status", help="Show recent runs")
    p.add_argument("--limit", type=int, default=20, help="Number of runs to show")

    # clean
    p = subparsers.add_parser("clean", help="Clean up agent worktrees", parents=[shared])
    p.add_argument("--force", action="store_true", help="Actually remove worktrees")

    # tools
    p = subparsers.add_parser("tools", help="List registered MCP tools")

    # dashboard
    p = subparsers.add_parser("dashboard", help="Open local web dashboard")
    p.add_argument("--port", type=int, default=7777, help="Port (default: 7777)")

    args = parser.parse_args()
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    # Commands that don't need API key
    no_key_commands = {"status", "clean", "dashboard", "tools"}

    if args.command not in no_key_commands:
        check_api_key()
        install_stderr_filter()

    # Sync commands
    sync_handlers = {
        "status": cmd_status,
        "clean": cmd_clean,
        "tools": cmd_tools,
        "dashboard": cmd_dashboard,
    }
    if args.command in sync_handlers:
        sync_handlers[args.command](args, config)
        return

    async_handlers = {
        "fix": cmd_fix,
        "test": cmd_test,
        "review": cmd_review,
        "build": cmd_build,
        "resume": cmd_resume,
        "batch": cmd_batch,
    }

    handler = async_handlers[args.command]
    asyncio.run(handler(args, config))


if __name__ == "__main__":
    main()
