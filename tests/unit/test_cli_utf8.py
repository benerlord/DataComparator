"""Regression tests for UTF-8 stdio reconfigure on Windows.

Without _ensure_utf8_stdio, Click/Typer's echo escapes ❌ to '\\u274c'
when stderr encoding is GBK (Windows default).
"""
import io
import sys
from unittest.mock import MagicMock, patch

from datacompare.cli import _ensure_utf8_stdio


def test_ensure_utf8_stdio_calls_reconfigure_on_streams():
    mock_stdout = MagicMock()
    mock_stderr = MagicMock()
    mock_stdout.reconfigure = MagicMock()
    mock_stderr.reconfigure = MagicMock()

    with patch.object(sys, "stdout", mock_stdout), patch.object(sys, "stderr", mock_stderr):
        _ensure_utf8_stdio()

    mock_stdout.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")
    mock_stderr.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")


def test_ensure_utf8_stdio_tolerates_stream_without_reconfigure():
    """pytest capture, BytesIO, and other non-file streams lack .reconfigure."""
    fake = io.BytesIO()
    with patch.object(sys, "stdout", fake), patch.object(sys, "stderr", fake):
        _ensure_utf8_stdio()  # must not raise


def test_ensure_utf8_stdio_tolerates_reconfigure_raising_oserror():
    mock = MagicMock()
    mock.reconfigure.side_effect = OSError("not a real tty")
    with patch.object(sys, "stdout", mock), patch.object(sys, "stderr", mock):
        _ensure_utf8_stdio()  # must not raise
