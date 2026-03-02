"""Suppress noisy stderr from the Claude CLI subprocess.

The Claude CLI has internal hooks (skill improvement, etc.) that write
stack traces to stderr when streams close. These are non-fatal and
cosmetic but make the output unreadable. This module filters them out.
"""

from __future__ import annotations

import io
import os
import sys


class StderrFilter(io.TextIOWrapper):
    """Filter out known noise patterns from stderr."""

    NOISE_PATTERNS = (
        "Error in hook callback",
        "error: Stream closed",
        "at sendRequest",
        "at <anonymous>",
        "skill_improvement",
        "hookSpecificOutput",
        "permissionDecision",
        "/$bunfs/root/claude",
    )

    def __init__(self, original: io.TextIOBase):
        self._original = original
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        # Only flush complete lines
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if not any(p in line for p in self.NOISE_PATTERNS):
                self._original.write(line + "\n")
                self._original.flush()
        return len(text)

    def flush(self) -> None:
        if self._buffer and not any(p in self._buffer for p in self.NOISE_PATTERNS):
            self._original.write(self._buffer)
            self._original.flush()
        self._buffer = ""

    def fileno(self) -> int:
        return self._original.fileno()

    def isatty(self) -> bool:
        return False


def install_stderr_filter() -> None:
    """Replace sys.stderr with a filtered version."""
    if not isinstance(sys.stderr, StderrFilter):
        sys.stderr = StderrFilter(sys.stderr)  # type: ignore[assignment]


def uninstall_stderr_filter() -> None:
    """Restore original stderr."""
    if isinstance(sys.stderr, StderrFilter):
        sys.stderr = sys.stderr._original  # type: ignore[assignment]
