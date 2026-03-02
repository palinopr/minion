"""Base blueprint -- the orchestration pattern that combines code + agent.

This is the equivalent of Stripe's blueprint engine.
A blueprint is a sequence of steps, some deterministic (code), some agentic (LLM).
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class StepType(Enum):
    DETERMINISTIC = "deterministic"
    AGENT = "agent"


@dataclass
class StepResult:
    success: bool
    output: str = ""
    duration_seconds: float = 0.0


@dataclass
class BlueprintResult:
    success: bool
    steps: list[StepResult] = field(default_factory=list)
    session_id: str | None = None
    branch: str = ""
    pr_url: str | None = None
    total_duration: float = 0.0


def run_shell(cmd: str, cwd: str, timeout: int = 120) -> StepResult:
    """Run a deterministic shell step. Returns structured result."""
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = time.time() - start
        output = (result.stdout + result.stderr).strip()
        return StepResult(
            success=result.returncode == 0,
            output=output,
            duration_seconds=duration,
        )
    except subprocess.TimeoutExpired:
        return StepResult(
            success=False,
            output=f"Command timed out after {timeout}s: {cmd}",
            duration_seconds=timeout,
        )
    except Exception as e:
        return StepResult(
            success=False,
            output=str(e),
            duration_seconds=time.time() - start,
        )


def format_step_log(step_num: int, step_type: StepType, description: str, result: StepResult) -> str:
    """Format a step result for console output."""
    icon = "OK" if result.success else "FAIL"
    kind = "CODE" if step_type == StepType.DETERMINISTIC else "AGENT"
    return (
        f"  [{icon}] Step {step_num} ({kind}): {description} "
        f"({result.duration_seconds:.1f}s)"
    )
