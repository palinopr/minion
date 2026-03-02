"""Tests for minion.history -- run history persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest

from minion.history import format_run_table, list_runs, save_run


# ── Stub for BlueprintResult (avoid importing the real one) ──────────

@dataclass
class _StepResult:
    success: bool
    output: str = ""
    duration_seconds: float = 0.0


@dataclass
class _BlueprintResult:
    success: bool
    steps: list[_StepResult] = field(default_factory=list)
    session_id: str | None = None
    branch: str = ""
    pr_url: str | None = None
    total_duration: float = 0.0
    total_cost_usd: float = 0.0


def _make_result(**overrides) -> _BlueprintResult:
    defaults = dict(
        success=True,
        steps=[_StepResult(success=True, output="ok", duration_seconds=1.5)],
        session_id="sess-abc",
        branch="agent/fix-1",
        pr_url="https://github.com/o/r/pull/1",
        total_duration=42.0,
        total_cost_usd=0.12,
    )
    defaults.update(overrides)
    return _BlueprintResult(**defaults)


# ── save_run ─────────────────────────────────────────────────────────


class TestSaveRun:
    def test_creates_json_file(self, tmp_path: Path):
        with patch("minion.history.HISTORY_DIR", tmp_path / "hist"):
            path = save_run("fix", "fix the bug", "/repo", "t1", _make_result())
        assert path.exists()
        assert path.suffix == ".json"

    def test_json_contains_command(self, tmp_path: Path):
        with patch("minion.history.HISTORY_DIR", tmp_path / "hist"):
            path = save_run("build", "build feature", "/repo", "t2", _make_result())
        data = json.loads(path.read_text())
        assert data["command"] == "build"

    def test_json_contains_description(self, tmp_path: Path):
        with patch("minion.history.HISTORY_DIR", tmp_path / "hist"):
            path = save_run("fix", "fix auth", "/repo", "t3", _make_result())
        data = json.loads(path.read_text())
        assert data["description"] == "fix auth"

    def test_json_contains_result_fields(self, tmp_path: Path):
        with patch("minion.history.HISTORY_DIR", tmp_path / "hist"):
            path = save_run("fix", "d", "/repo", "t4", _make_result())
        data = json.loads(path.read_text())
        assert data["success"] is True
        assert data["branch"] == "agent/fix-1"
        assert data["pr_url"] == "https://github.com/o/r/pull/1"
        assert data["total_duration"] == 42.0
        assert data["total_cost_usd"] == 0.12

    def test_json_contains_steps(self, tmp_path: Path):
        with patch("minion.history.HISTORY_DIR", tmp_path / "hist"):
            path = save_run("fix", "d", "/repo", "t5", _make_result())
        data = json.loads(path.read_text())
        assert len(data["steps"]) == 1
        assert data["steps"][0]["success"] is True

    def test_creates_history_dir_if_missing(self, tmp_path: Path):
        hist = tmp_path / "deep" / "hist"
        with patch("minion.history.HISTORY_DIR", hist):
            save_run("fix", "d", "/repo", "t6", _make_result())
        assert hist.is_dir()

    def test_failed_result_records_success_false(self, tmp_path: Path):
        with patch("minion.history.HISTORY_DIR", tmp_path / "hist"):
            path = save_run("fix", "d", "/repo", "t7", _make_result(success=False))
        data = json.loads(path.read_text())
        assert data["success"] is False

    def test_none_pr_url(self, tmp_path: Path):
        with patch("minion.history.HISTORY_DIR", tmp_path / "hist"):
            path = save_run("fix", "d", "/repo", "t8", _make_result(pr_url=None))
        data = json.loads(path.read_text())
        assert data["pr_url"] is None

    def test_filename_contains_command_and_task_id(self, tmp_path: Path):
        with patch("minion.history.HISTORY_DIR", tmp_path / "hist"):
            path = save_run("build", "d", "/repo", "task42", _make_result())
        assert "build" in path.name
        assert "task42" in path.name


# ── list_runs ────────────────────────────────────────────────────────


class TestListRuns:
    def test_returns_empty_when_no_history_dir(self, tmp_path: Path):
        with patch("minion.history.HISTORY_DIR", tmp_path / "nonexistent"):
            assert list_runs() == []

    def test_returns_empty_when_dir_has_no_json(self, tmp_path: Path):
        hist = tmp_path / "hist"
        hist.mkdir()
        with patch("minion.history.HISTORY_DIR", hist):
            assert list_runs() == []

    def test_returns_saved_runs(self, tmp_path: Path):
        hist = tmp_path / "hist"
        with patch("minion.history.HISTORY_DIR", hist):
            save_run("fix", "d1", "/repo", "t1", _make_result())
            save_run("build", "d2", "/repo", "t2", _make_result())
            runs = list_runs()
        assert len(runs) == 2

    def test_respects_limit(self, tmp_path: Path):
        hist = tmp_path / "hist"
        with patch("minion.history.HISTORY_DIR", hist):
            for i in range(5):
                save_run("fix", f"d{i}", "/repo", f"t{i}", _make_result())
            runs = list_runs(limit=2)
        assert len(runs) == 2

    def test_most_recent_first(self, tmp_path: Path):
        hist = tmp_path / "hist"
        hist.mkdir()
        # Manually write files with ordered timestamps
        for i, ts in enumerate(["20240101_000000", "20240102_000000", "20240103_000000"]):
            fpath = hist / f"{ts}_fix_t{i}.json"
            fpath.write_text(json.dumps({"command": f"fix{i}", "timestamp": ts}))
        with patch("minion.history.HISTORY_DIR", hist):
            runs = list_runs()
        assert runs[0]["timestamp"] == "20240103_000000"


# ── format_run_table ─────────────────────────────────────────────────


class TestFormatRunTable:
    def test_empty_list(self):
        assert format_run_table([]) == "No runs found."

    def test_contains_header_line(self):
        runs = [
            {
                "timestamp": "20240101_120000",
                "command": "fix",
                "success": True,
                "total_duration": 30.0,
                "total_cost_usd": 0.05,
                "description": "fix the thing",
                "pr_url": "",
            }
        ]
        table = format_run_table(runs)
        assert "Time" in table
        assert "Cmd" in table

    def test_shows_yes_for_success(self):
        runs = [
            {
                "timestamp": "20240101_120000",
                "command": "fix",
                "success": True,
                "total_duration": 30.0,
                "total_cost_usd": 0.05,
                "description": "fix it",
                "pr_url": "",
            }
        ]
        table = format_run_table(runs)
        assert "yes" in table

    def test_shows_fail_for_failure(self):
        runs = [
            {
                "timestamp": "20240101_120000",
                "command": "fix",
                "success": False,
                "total_duration": 30.0,
                "total_cost_usd": 0.05,
                "description": "fix it",
                "pr_url": "",
            }
        ]
        table = format_run_table(runs)
        assert "FAIL" in table

    def test_truncates_long_description(self):
        runs = [
            {
                "timestamp": "20240101_120000",
                "command": "fix",
                "success": True,
                "total_duration": 30.0,
                "total_cost_usd": 0.05,
                "description": "A" * 100,
                "pr_url": "",
            }
        ]
        table = format_run_table(runs)
        # The 100-char description is truncated to 40
        assert "A" * 41 not in table

    def test_handles_missing_cost_key(self):
        runs = [
            {
                "timestamp": "20240101_120000",
                "command": "fix",
                "success": True,
                "total_duration": 30.0,
                "description": "fix it",
                "pr_url": "",
            }
        ]
        table = format_run_table(runs)
        assert "$0.00" in table
