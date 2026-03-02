"""Run history -- log every minion run so you can see what happened."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

from minion.blueprints.base import BlueprintResult

HISTORY_DIR = Path(__file__).parent.parent / ".minion_history"


def save_run(
    command: str,
    description: str,
    repo_path: str,
    task_id: str,
    result: BlueprintResult,
) -> Path:
    """Save a completed run to the history directory."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{command}_{task_id}.json"
    filepath = HISTORY_DIR / filename

    record = {
        "timestamp": timestamp,
        "command": command,
        "description": description,
        "repo_path": repo_path,
        "task_id": task_id,
        "success": result.success,
        "branch": result.branch,
        "pr_url": result.pr_url,
        "total_duration": result.total_duration,
        "session_id": result.session_id,
        "steps": [asdict(s) for s in result.steps],
    }

    with open(filepath, "w") as f:
        json.dump(record, f, indent=2)

    return filepath


def list_runs(limit: int = 20) -> list[dict]:
    """List recent runs from history."""
    if not HISTORY_DIR.exists():
        return []

    files = sorted(HISTORY_DIR.glob("*.json"), reverse=True)[:limit]
    runs = []
    for f in files:
        with open(f) as fh:
            runs.append(json.load(fh))
    return runs


def format_run_table(runs: list[dict]) -> str:
    """Format runs as a readable table."""
    if not runs:
        return "No runs found."

    lines = [
        f"{'Time':<17} {'Cmd':<7} {'OK?':<5} {'Duration':<10} {'Description':<40} {'PR':<10}",
        "-" * 95,
    ]
    for r in runs:
        ok = "yes" if r["success"] else "FAIL"
        dur = f"{r['total_duration']:.0f}s"
        desc = r["description"][:40]
        pr = r.get("pr_url", "") or ""
        pr = pr[-30:] if len(pr) > 30 else pr
        lines.append(
            f"{r['timestamp']:<17} {r['command']:<7} {ok:<5} {dur:<10} {desc:<40} {pr:<10}"
        )
    return "\n".join(lines)
