"""Local dashboard -- view minion runs, diffs, and logs.

Run with: minion dashboard
Opens at http://localhost:7777
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from flask import Flask, Response

from minion.history import HISTORY_DIR

app = Flask(__name__)


def get_runs() -> list[dict]:
    """Load all runs from history, newest first."""
    if not HISTORY_DIR.exists():
        return []
    files = sorted(HISTORY_DIR.glob("*.json"), reverse=True)
    runs = []
    for f in files:
        with open(f) as fh:
            run = json.load(fh)
            run["_file"] = f.name
            runs.append(run)
    return runs


def get_diff(repo_path: str, branch: str, base: str = "main") -> str:
    """Get the git diff for a branch."""
    try:
        result = subprocess.run(
            ["git", "diff", f"{base}...{branch}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout or "No diff available"
    except Exception:
        return "Could not generate diff"


@app.route("/")
def index() -> str:
    runs = get_runs()

    rows = ""
    for r in runs:
        status_class = "ok" if r["success"] else "fail"
        status_text = "OK" if r["success"] else "FAIL"
        dur = f"{r.get('total_duration', 0):.0f}s"
        pr = r.get("pr_url") or ""
        pr_link = f'<a href="{pr}" target="_blank">PR</a>' if pr else "-"
        desc = r["description"][:60]
        branch = r.get("branch", "")
        file_id = r["_file"].replace(".json", "")

        rows += f"""
        <tr class="{status_class}">
            <td>{r['timestamp']}</td>
            <td><span class="badge {status_class}">{r['command']}</span></td>
            <td class="status-{status_class}">{status_text}</td>
            <td>{dur}</td>
            <td title="{r['description']}">{desc}</td>
            <td><code>{branch}</code></td>
            <td>{pr_link}</td>
            <td><a href="/run/{file_id}">details</a></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Minion Dashboard</title>
    <meta http-equiv="refresh" content="10">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, SF Mono, monospace; background: #0d1117; color: #c9d1d9; padding: 24px; }}
        h1 {{ font-size: 20px; margin-bottom: 16px; color: #f0f6fc; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th {{ text-align: left; padding: 8px 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-weight: 500; }}
        td {{ padding: 8px 12px; border-bottom: 1px solid #21262d; }}
        tr:hover {{ background: #161b22; }}
        .badge {{ padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; text-transform: uppercase; }}
        .badge.ok {{ background: #1a3a2a; color: #3fb950; }}
        .badge.fail {{ background: #3d1f1f; color: #f85149; }}
        .status-ok {{ color: #3fb950; }}
        .status-fail {{ color: #f85149; font-weight: 600; }}
        a {{ color: #58a6ff; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        code {{ background: #161b22; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
        .empty {{ text-align: center; padding: 48px; color: #8b949e; }}
        .stats {{ display: flex; gap: 24px; margin-bottom: 20px; }}
        .stat {{ background: #161b22; padding: 12px 20px; border-radius: 8px; border: 1px solid #30363d; }}
        .stat-value {{ font-size: 24px; font-weight: 700; color: #f0f6fc; }}
        .stat-label {{ font-size: 11px; color: #8b949e; text-transform: uppercase; margin-top: 4px; }}
    </style>
</head>
<body>
    <h1>Minion Dashboard</h1>
    <div class="stats">
        <div class="stat">
            <div class="stat-value">{len(runs)}</div>
            <div class="stat-label">Total Runs</div>
        </div>
        <div class="stat">
            <div class="stat-value">{sum(1 for r in runs if r['success'])}</div>
            <div class="stat-label">Succeeded</div>
        </div>
        <div class="stat">
            <div class="stat-value">{sum(1 for r in runs if not r['success'])}</div>
            <div class="stat-label">Failed</div>
        </div>
    </div>
    {'<table><thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Duration</th><th>Description</th><th>Branch</th><th>PR</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>' if runs else '<div class="empty">No runs yet. Run a minion command to see results here.</div>'}
</body>
</html>"""


@app.route("/run/<file_id>")
def run_detail(file_id: str) -> str | tuple[str, int]:
    filepath = HISTORY_DIR / f"{file_id}.json"
    if not filepath.exists():
        return "Run not found", 404

    with open(filepath) as f:
        run = json.load(f)

    # Get diff if branch exists
    diff_html = ""
    if run.get("branch") and run.get("repo_path"):
        diff = get_diff(run["repo_path"], run["branch"])
        # Basic syntax highlighting for diff
        diff_lines = []
        for line in diff.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                diff_lines.append(f'<span class="diff-add">{_esc(line)}</span>')
            elif line.startswith("-") and not line.startswith("---"):
                diff_lines.append(f'<span class="diff-del">{_esc(line)}</span>')
            elif line.startswith("@@"):
                diff_lines.append(f'<span class="diff-hunk">{_esc(line)}</span>')
            else:
                diff_lines.append(_esc(line))
        diff_html = "\n".join(diff_lines)

    steps_html = ""
    for i, step in enumerate(run.get("steps", [])):
        ok = step.get("success", False)
        cls = "ok" if ok else "fail"
        dur = f"{step.get('duration_seconds', 0):.1f}s"
        output = step.get("output", "")[:500]
        steps_html += f"""
        <div class="step {cls}">
            <div class="step-header">
                <span class="status-{cls}">{'OK' if ok else 'FAIL'}</span>
                Step {i + 1} ({dur})
            </div>
            {'<pre class="step-output">' + _esc(output) + '</pre>' if output else ''}
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Run: {run.get('command', '')} - {run.get('task_id', '')}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, SF Mono, monospace; background: #0d1117; color: #c9d1d9; padding: 24px; }}
        h1 {{ font-size: 18px; margin-bottom: 4px; color: #f0f6fc; }}
        h2 {{ font-size: 14px; color: #8b949e; margin: 20px 0 8px; text-transform: uppercase; }}
        .meta {{ color: #8b949e; font-size: 13px; margin-bottom: 20px; }}
        a {{ color: #58a6ff; text-decoration: none; }}
        .step {{ margin: 8px 0; padding: 8px 12px; border-left: 3px solid #30363d; background: #161b22; border-radius: 0 6px 6px 0; }}
        .step.ok {{ border-left-color: #3fb950; }}
        .step.fail {{ border-left-color: #f85149; }}
        .step-header {{ font-size: 13px; font-weight: 600; }}
        .step-output {{ font-size: 12px; color: #8b949e; margin-top: 6px; white-space: pre-wrap; max-height: 200px; overflow-y: auto; }}
        .status-ok {{ color: #3fb950; }}
        .status-fail {{ color: #f85149; }}
        pre.diff {{ background: #161b22; padding: 16px; border-radius: 8px; font-size: 12px; overflow-x: auto; border: 1px solid #30363d; max-height: 600px; overflow-y: auto; }}
        .diff-add {{ color: #3fb950; }}
        .diff-del {{ color: #f85149; }}
        .diff-hunk {{ color: #a371f7; }}
        .back {{ margin-bottom: 16px; display: inline-block; }}
    </style>
</head>
<body>
    <a class="back" href="/">back to dashboard</a>
    <h1>{run.get('command', '').upper()}: {_esc(run.get('description', '')[:80])}</h1>
    <div class="meta">
        Task: {run.get('task_id', '')} | Branch: <code>{run.get('branch', '')}</code> |
        Duration: {run.get('total_duration', 0):.0f}s |
        Status: <span class="status-{'ok' if run['success'] else 'fail'}">{'OK' if run['success'] else 'FAIL'}</span>
    </div>

    <h2>Steps</h2>
    {steps_html or '<div>No steps recorded</div>'}

    <h2>Diff</h2>
    <pre class="diff">{diff_html or 'No diff available'}</pre>
</body>
</html>"""


def _esc(text: str) -> str:
    """Escape HTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def run_dashboard(port: int = 7777) -> None:
    """Start the dashboard server."""
    print(f"Minion dashboard: http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
