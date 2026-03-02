"""Tests for minion.quiet -- noise suppression for CLI output."""

from __future__ import annotations

import io
import sys

import pytest

from minion.quiet import (
    OutputFilter,
    _is_noise,
    install_stderr_filter,
    uninstall_stderr_filter,
)


# ── _is_noise ────────────────────────────────────────────────────────


class TestIsNoisePatternMatching:
    """Lines matching known noise patterns are detected."""

    def test_hook_callback_error(self):
        assert _is_noise("Error in hook callback: something broke") is True

    def test_stream_closed(self):
        assert _is_noise("error: Stream closed unexpectedly") is True

    def test_bunfs_path(self):
        assert _is_noise("at something (/$bunfs/root/claude)") is True

    def test_skill_improvement(self):
        assert _is_noise('{"type":"skill_improvement","data":{}}') is True

    def test_permission_decision(self):
        assert _is_noise("permissionDecision: allow") is True

    def test_thinking_config(self):
        assert _is_noise("thinkingConfig: {budget: 10000}") is True

    def test_control_request(self):
        assert _is_noise("control_request sent to server") is True

    def test_send_request_pattern(self):
        assert _is_noise("at sendRequest (internal:3:42)") is True

    def test_cannot_call_impure(self):
        assert _is_noise("Cannot call impure function in context") is True


class TestIsNoiseLineNumberPattern:
    """Lines that look like minified JS line numbers are noise."""

    def test_four_digit_line_number(self):
        assert _is_noise("  1234 | var x = function(){}") is True

    def test_five_digit_line_number(self):
        assert _is_noise("56789 | module.exports") is True

    def test_three_digit_is_not_noise(self):
        # 3-digit numbers don't match the minified-JS heuristic
        assert _is_noise("  123 | normal line") is False


class TestIsNoiseLongMinifiedLine:
    """Long lines with very few spaces are noise (minified JS)."""

    def test_long_dense_line_is_noise(self):
        # 400 chars with <8% spaces
        line = "a" * 380 + " " * 20  # 5% spaces
        assert _is_noise(line) is True

    def test_long_normal_line_is_not_noise(self):
        # 400 chars but ~25% spaces -- normal prose
        line = ("word " * 80)[:400]
        assert _is_noise(line) is False

    def test_short_dense_line_is_not_noise(self):
        # Under 300 chars, even dense text is not flagged
        line = "a" * 200
        assert _is_noise(line) is False


class TestIsNoiseCleanLines:
    """Normal output lines should not be filtered."""

    def test_normal_log_line(self):
        assert _is_noise("Running pytest --tb=short -q") is False

    def test_empty_line(self):
        assert _is_noise("") is False

    def test_normal_error(self):
        assert _is_noise("TypeError: cannot read property 'x' of undefined") is False

    def test_short_line(self):
        assert _is_noise("OK") is False

    def test_python_traceback(self):
        assert _is_noise('  File "/app/main.py", line 42, in run') is False

    def test_git_output(self):
        assert _is_noise("Already up to date.") is False


# ── OutputFilter ─────────────────────────────────────────────────────


class TestOutputFilter:
    def _make_filter(self) -> tuple[OutputFilter, io.StringIO]:
        buf = io.StringIO()
        return OutputFilter(buf), buf

    def test_passes_normal_line(self):
        filt, buf = self._make_filter()
        filt.write("hello world\n")
        assert buf.getvalue() == "hello world\n"

    def test_drops_noise_line(self):
        filt, buf = self._make_filter()
        filt.write("Error in hook callback: blah\n")
        assert buf.getvalue() == ""

    def test_buffers_until_newline(self):
        filt, buf = self._make_filter()
        filt.write("partial")
        assert buf.getvalue() == ""
        filt.write(" line\n")
        assert "partial line" in buf.getvalue()

    def test_handles_multiple_lines_in_one_write(self):
        filt, buf = self._make_filter()
        filt.write("line1\nline2\n")
        assert "line1" in buf.getvalue()
        assert "line2" in buf.getvalue()

    def test_filters_noise_among_good_lines(self):
        filt, buf = self._make_filter()
        filt.write("good line\nError in hook callback: bad\nanother good\n")
        output = buf.getvalue()
        assert "good line" in output
        assert "another good" in output
        assert "hook callback" not in output

    def test_flush_writes_buffered_content(self):
        filt, buf = self._make_filter()
        filt.write("no newline yet")
        filt.flush()
        assert "no newline yet" in buf.getvalue()

    def test_flush_drops_noise_in_buffer(self):
        filt, buf = self._make_filter()
        filt.write("Error in hook callback: stuff")
        filt.flush()
        assert buf.getvalue() == ""

    def test_write_returns_input_length(self):
        filt, buf = self._make_filter()
        assert filt.write("hello\n") == 6

    def test_isatty_returns_false(self):
        filt, _ = self._make_filter()
        assert filt.isatty() is False

    def test_fileno_delegates_to_original(self):
        filt, buf = self._make_filter()
        # StringIO doesn't have fileno, so this should raise
        with pytest.raises(io.UnsupportedOperation):
            filt.fileno()

    def test_getattr_delegates_to_original(self):
        filt, buf = self._make_filter()
        # StringIO has a 'closed' attribute
        assert filt.closed is False


# ── install / uninstall ──────────────────────────────────────────────


class TestInstallUninstall:
    def test_install_replaces_streams(self):
        orig_out = sys.stdout
        orig_err = sys.stderr
        try:
            # Reset the guard
            import minion.quiet as q
            q._installed = False
            install_stderr_filter()
            assert isinstance(sys.stdout, OutputFilter)
            assert isinstance(sys.stderr, OutputFilter)
        finally:
            uninstall_stderr_filter()
            sys.stdout = orig_out
            sys.stderr = orig_err

    def test_uninstall_restores_streams(self):
        orig_out = sys.stdout
        orig_err = sys.stderr
        try:
            import minion.quiet as q
            q._installed = False
            install_stderr_filter()
            uninstall_stderr_filter()
            assert not isinstance(sys.stdout, OutputFilter)
            assert not isinstance(sys.stderr, OutputFilter)
        finally:
            sys.stdout = orig_out
            sys.stderr = orig_err

    def test_double_install_is_safe(self):
        orig_out = sys.stdout
        orig_err = sys.stderr
        try:
            import minion.quiet as q
            q._installed = False
            install_stderr_filter()
            install_stderr_filter()  # second call should be no-op
            assert isinstance(sys.stdout, OutputFilter)
            uninstall_stderr_filter()
        finally:
            sys.stdout = orig_out
            sys.stderr = orig_err

    def test_uninstall_without_install_is_safe(self):
        import minion.quiet as q
        q._installed = False
        uninstall_stderr_filter()  # should not crash
