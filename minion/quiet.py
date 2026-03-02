"""Suppress noisy stderr/stdout from the Claude CLI subprocess.

The Claude CLI has internal hooks (skill improvement, etc.) that write
stack traces and minified JS to stderr/stdout when streams close. These
are non-fatal and cosmetic but make output unreadable.

Two-layer approach:
1. Python-level: OutputFilter wraps sys.stdout/sys.stderr for output
   from Python code (print statements, logging).
2. Env-level: Sets PYTHONUNBUFFERED so subprocess output interleaves
   correctly with filtered output.

The Claude Agent SDK passes debug_stderr=devnull to suppress some noise,
but hook callback errors slip through. This filter catches the rest.
"""

from __future__ import annotations

import io
import re
import sys

# Every pattern that appears in CLI noise. Any line matching = drop it.
_NOISE_PATTERNS = (
    "Error in hook callback",
    "error: Stream closed",
    "at sendRequest",
    "at <anonymous>",
    "/$bunfs/root/claude",
    "at next (1:",
    "at A (/$bunfs",
    "at UVR (",
    "at ok (",
    "at sb8 (",
    "skill_improvement",
    "hookSpecificOutput",
    "permissionDecision",
    "skill_improvement_apply",
    "updated_file",
    "Preserve frontmatter",
    "Preserve the overall format",
    "Integrate the improvements",
    "Output the complete updated",
    "Do not remove existing content",
    "thinkingConfig",
    "isNonInteractiveSession",
    "getToolPermissionContext",
    "cleanupPeriodDays",
    "sendRequest(T,R,A)",
    "inputClosed",
    "trackResolvedToolUseId",
    "createCanUseTool",
    "Cannot call impure function",
    "ResolveIdContext",
    "EnvironmentPluginContainer",
    "TransformPluginContext",
    "systemPrompt:P0(",
    "message.content.filter",
    "writeFile(B,O",
    "mcpTools:[]",
    "querySource:",
    "temperatureOverride",
    "hasAppendSystemPrompt",
    "toolChoice:void",
    "permissionMode",
    "control_request",
    "control_cancel_request",
    "pendingRequests",
)

_NOISE_RE = re.compile("|".join(re.escape(p) for p in _NOISE_PATTERNS))
_LINENUM_RE = re.compile(r"^\s*\d{4,}\s*\|")


def _is_noise(line: str) -> bool:
    """Check if a line is CLI noise that should be dropped."""
    if _NOISE_RE.search(line):
        return True
    if _LINENUM_RE.match(line):
        return True
    if len(line) > 300 and line.count(" ") < len(line) * 0.08:
        return True
    return False


class OutputFilter:
    """Line-buffered filter that drops noise from an output stream."""

    def __init__(self, original: io.TextIOBase):
        self._original = original
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if not _is_noise(line):
                self._original.write(line + "\n")
                self._original.flush()
        return len(text)

    def flush(self) -> None:
        if self._buffer and not _is_noise(self._buffer):
            self._original.write(self._buffer)
            self._original.flush()
        self._buffer = ""

    def fileno(self) -> int:
        return self._original.fileno()

    def isatty(self) -> bool:
        return False

    # Delegate everything else to the original stream
    def __getattr__(self, name: str):
        return getattr(self._original, name)


_installed = False


def install_stderr_filter() -> None:
    """Replace sys.stderr and sys.stdout with filtered versions."""
    global _installed
    if _installed:
        return
    _installed = True

    if not isinstance(sys.stderr, OutputFilter):
        sys.stderr = OutputFilter(sys.stderr)  # type: ignore[assignment]

    if not isinstance(sys.stdout, OutputFilter):
        sys.stdout = OutputFilter(sys.stdout)  # type: ignore[assignment]


def uninstall_stderr_filter() -> None:
    """Restore original streams."""
    global _installed
    if not _installed:
        return

    if isinstance(sys.stderr, OutputFilter):
        sys.stderr = sys.stderr._original  # type: ignore[assignment]
    if isinstance(sys.stdout, OutputFilter):
        sys.stdout = sys.stdout._original  # type: ignore[assignment]

    _installed = False
