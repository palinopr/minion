"""Suppress noisy stderr from the Claude CLI subprocess.

The Claude CLI has internal hooks (skill improvement, etc.) that write
stack traces to stderr when streams close. These are non-fatal and
cosmetic but make the output unreadable. This module filters them out.

The noise comes through both stderr and stdout because the SDK spawns
the CLI as a subprocess. We filter both streams.
"""

from __future__ import annotations

import io
import sys


class OutputFilter(io.TextIOWrapper):
    """Filter out known noise patterns from an output stream."""

    NOISE_PATTERNS = (
        # CLI hook errors (fires on every tool use when stream closes)
        "Error in hook callback",
        "error: Stream closed",
        # Stack traces from the bundled CLI binary
        "at sendRequest",
        "at <anonymous>",
        "/$bunfs/root/claude",
        "at next (1:",
        "at A (/$bunfs",
        "at UVR (",
        "at ok (",
        "at sb8 (",
        # Internal hook subsystems
        "skill_improvement",
        "hookSpecificOutput",
        "permissionDecision",
        "skill_improvement_apply",
        "updated_file",
        # Minified code dumps from CLI internals
        "Preserve frontmatter",
        "Integrate the improvements",
        "Output the complete updated",
        "thinkingConfig",
        "isNonInteractiveSession",
        "getToolPermissionContext",
        "cleanupPeriodDays",
        "sendRequest(T,R,A)",
        "inputClosed",
        "trackResolvedToolUseId",
        "createCanUseTool",
        # Long minified lines (>500 chars with no spaces = likely bundled JS)
        # Handled via length check below
    )

    def __init__(self, original: io.TextIOBase):
        self._original = original
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if not self._is_noise(line):
                self._original.write(line + "\n")
                self._original.flush()
        return len(text)

    def _is_noise(self, line: str) -> bool:
        """Check if a line is CLI noise that should be suppressed."""
        if any(p in line for p in self.NOISE_PATTERNS):
            return True
        # Lines >500 chars with very few spaces are likely minified JS dumps
        if len(line) > 500 and line.count(" ") < len(line) * 0.05:
            return True
        return False

    def flush(self) -> None:
        if self._buffer and not self._is_noise(self._buffer):
            self._original.write(self._buffer)
            self._original.flush()
        self._buffer = ""

    def fileno(self) -> int:
        return self._original.fileno()

    def isatty(self) -> bool:
        return False


_original_stderr = None
_original_stdout = None


def install_stderr_filter() -> None:
    """Replace sys.stderr and sys.stdout with filtered versions."""
    global _original_stderr, _original_stdout

    if not isinstance(sys.stderr, OutputFilter):
        _original_stderr = sys.stderr
        sys.stderr = OutputFilter(sys.stderr)  # type: ignore[assignment]

    if not isinstance(sys.stdout, OutputFilter):
        _original_stdout = sys.stdout
        sys.stdout = OutputFilter(sys.stdout)  # type: ignore[assignment]


def uninstall_stderr_filter() -> None:
    """Restore original streams."""
    global _original_stderr, _original_stdout

    if _original_stderr and isinstance(sys.stderr, OutputFilter):
        sys.stderr = _original_stderr  # type: ignore[assignment]
    if _original_stdout and isinstance(sys.stdout, OutputFilter):
        sys.stdout = _original_stdout  # type: ignore[assignment]
