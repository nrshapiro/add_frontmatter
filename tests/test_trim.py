"""Regression tests for add_frontmatter.trim, using small real video+chat-log
fixtures under tests/fixtures/ (see that folder's own files).

These exist because two real bugs shipped unnoticed: the "!START"-only
marker match (missed a host's "iStart" typo) and the wall-clock-vs-elapsed
chat-log timestamp confusion (silently skipped a trim that should have
worked). Both are exercised here against real ffmpeg runs, not mocks, so a
future change to the offset math or marker matching gets caught before it
reaches a real meeting recording.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from add_frontmatter.core import FfmpegNotFoundError, get_ffmpeg_path
from add_frontmatter.trim import DEFAULT_TRIGGERS, is_elapsed_chat_log, maybe_trim

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def ffmpeg_path() -> str:
    try:
        return get_ffmpeg_path()
    except FfmpegNotFoundError as exc:
        pytest.skip(f"no ffmpeg available: {exc}")


def _video_in(folder_name: str) -> Path:
    return next((FIXTURES / folder_name).glob("*.mp4"))


def test_wallclock_chat_log_trims_at_marker(ffmpeg_path: str) -> None:
    """Classic "<prefix>_Recording.txt" chat log: timestamps are wall-clock
    time-of-day, anchored against the video's own GMT filename timestamp.
    Marker is 3 seconds after the video's (converted) start time."""
    video = _video_in("wallclock_chat")
    with tempfile.TemporaryDirectory() as tmp:
        working_video, msg, offset = maybe_trim(ffmpeg_path, video, Path(tmp), DEFAULT_TRIGGERS)
        assert offset == pytest.approx(3, abs=1), msg
        assert working_video != video, "should have produced a trimmed copy"
        assert working_video.is_file()
        assert "!START" in msg


def test_elapsed_chat_log_trims_at_marker(ffmpeg_path: str) -> None:
    """"<prefix>_RecordingnewChat.txt" variant: timestamps are elapsed time
    since recording start, used directly as the offset (no anchor). This
    is the 2026-10-22 bug -- feeding this into the wall-clock anchor math
    produced an implausible multi-hour offset that got silently rejected."""
    video = _video_in("elapsed_chat")
    chat = next((FIXTURES / "elapsed_chat").glob("*.txt"))
    assert is_elapsed_chat_log(chat)

    with tempfile.TemporaryDirectory() as tmp:
        working_video, msg, offset = maybe_trim(ffmpeg_path, video, Path(tmp), DEFAULT_TRIGGERS)
        assert offset == pytest.approx(2, abs=1), msg
        assert working_video != video
        assert working_video.is_file()
        assert "iStart" in msg


def test_chat_log_without_marker_skips_trim(ffmpeg_path: str) -> None:
    """A companion chat log that never mentions the marker should leave the
    video untouched (and never raise) -- not an error, just nothing to do."""
    video = _video_in("no_marker_chat")
    with tempfile.TemporaryDirectory() as tmp:
        working_video, msg, offset = maybe_trim(ffmpeg_path, video, Path(tmp), DEFAULT_TRIGGERS)
        assert offset is None
        assert working_video == video, "should pass the original through unchanged"
        assert "none of" in msg and "is in it" in msg


def test_wallclock_filename_is_not_flagged_as_elapsed() -> None:
    chat = next((FIXTURES / "wallclock_chat").glob("*.txt"))
    assert not is_elapsed_chat_log(chat)
