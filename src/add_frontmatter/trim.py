"""Auto-trim a Zoom recording's lead-in using a chat-log marker.

Ported from the standalone trim_zoom.py prototype into a library used as an
automatic first stage of process_video(): if a companion chat log is found
next to a video and it contains the trigger phrase (default "!START"), the
video is losslessly trimmed to start right at that marker before frontmatter
is prepended. If no chat log is found (or the marker isn't in it), the video
is passed through untouched -- so this is purely additive for anyone not
using the marker convention.

Zoom's chat log timestamps are real wall-clock time-of-day (e.g. "22:35:02"
meaning 10:35:02 PM, not "35 minutes 2 seconds into the meeting") -- this
was verified against a widely-used Zoom-chat-parsing tool
(zoomGroupStats' processZoomChat.R), which validates each timestamp against
a strict HH:MM:SS-of-day pattern and only afterward derives elapsed time by
subtracting a separately-known session start.

Computing the trim offset therefore means comparing two clocks: the chat
log's wall-clock time, and *some* notion of when the video itself started.
The original trim_zoom.py prototype (and an earlier version of this file)
got that second clock from the video's filename, containing folder, or
embedded metadata -- but the video's Zoom-assigned GMT filename prefix is
explicitly UTC, while the chat log's wall-clock timestamps are the
meeting host's LOCAL time. Comparing those directly silently introduces a
fixed multi-hour error (whatever the local UTC offset is) on any real
recording -- exactly the kind of large, wrong trim this bug report was
about, just from a different cause than the one that actually triggered it.

The fix: never cross-reference the video's clock against the chat log's
clock at all. Instead, anchor entirely *within the chat log itself* --
the timestamp of the chat log's OWN FIRST line stands in for "recording
start" (chat logging begins essentially when the meeting does, generally
at or before the point someone starts the recording), and the trim offset
is just (marker time - first line's time), both read off the same clock.
Time zone becomes irrelevant because nothing outside the chat log is ever
consulted. The remaining failure mode -- someone chatting well before the
host actually clicks Record -- only makes the script UNDER-trim (leaves a
bit more lead-in than strictly necessary), never wildly over-trim, which
is the safe direction to be wrong in.

Chat-log detection, in order of preference:
  1. A .txt file in the same folder sharing the video's own GMT prefix
     (e.g. "GMT20231018-225042_Recording.txt") -- this is how Zoom cloud
     recordings actually name their companion chat-log download, and it
     does NOT contain the word "chat" anywhere, so relying on that word
     alone (strategy 2) silently misses it.
  2. Any file matching *chat*.txt (case-insensitive) -- covers Zoom's local
     "meeting_saved_chat.txt" naming and anything hand-renamed to include
     "chat".
  3. If exactly one .txt file remains in the folder and neither of the
     above matched, use it (last-resort fallback for oddly-named files).
If none of these produce a candidate, or the trigger phrase isn't found in
whatever file is found, trimming is skipped entirely -- never an error.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path

DEFAULT_TRIGGER = "!START"

GMT_FILENAME_RE = re.compile(r"GMT(\d{8})-(\d{6})")
LINE_TIMESTAMP_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})")


def find_chat_file(video_path: Path) -> Path | None:
    """Returns the companion chat-log path, or None if nothing plausible
    is found (never raises -- absence just means "don't trim this one")."""
    folder = video_path.parent
    txt_files = sorted(folder.glob("*.txt"))
    if not txt_files:
        return None

    gmt_match = GMT_FILENAME_RE.search(video_path.name)
    if gmt_match:
        prefix = f"GMT{gmt_match.group(1)}-{gmt_match.group(2)}"
        same_prefix = [p for p in txt_files if p.name.startswith(prefix)]
        if same_prefix:
            return same_prefix[0]

    chat_named = [p for p in txt_files if "chat" in p.name.lower()]
    if chat_named:
        return chat_named[0]

    if len(txt_files) == 1:
        return txt_files[0]

    return None


def _parse_line_timestamp(line: str) -> dt_time | None:
    m = LINE_TIMESTAMP_RE.match(line.strip())
    if not m:
        return None
    h, mn, s = m.groups()
    return dt_time(int(h), int(mn), int(s))


def find_first_timestamp(chat_path: Path) -> tuple[dt_time | None, int]:
    """The chat log's own first timestamped line -- used as the "recording
    started here" anchor (see module docstring for why this, rather than
    the video's filename/metadata, is the right thing to anchor against)."""
    with open(chat_path, "r", encoding="utf-8", errors="ignore") as f:
        for lineno, line in enumerate(f, start=1):
            t = _parse_line_timestamp(line)
            if t is not None:
                return t, lineno
    return None, 0


def find_trigger_time(chat_path: Path, trigger: str) -> tuple[dt_time | None, int, str]:
    """Returns (time_or_None, line_number, matched_line_text). Uses the
    FIRST occurrence if the trigger appears more than once (e.g. someone
    tested it, then said it again for real -- the earlier one wins, same
    as the original trim_zoom.py prototype's behavior)."""
    with open(chat_path, "r", encoding="utf-8", errors="ignore") as f:
        for lineno, line in enumerate(f, start=1):
            if trigger.lower() in line.lower():
                t = _parse_line_timestamp(line)
                if t is not None:
                    return t, lineno, line.strip()
    return None, 0, ""


def compute_offset_seconds(anchor_time: dt_time, marker_time: dt_time) -> float:
    """Both times come from the SAME chat log, so they're already in the
    same clock/time zone -- no cross-referencing against the video's own
    clock needed (see module docstring). Combined onto an arbitrary shared
    date purely so timedelta arithmetic works; only the difference matters."""
    anchor_dt = datetime.combine(datetime(2000, 1, 1), anchor_time)
    marker_dt = datetime.combine(datetime(2000, 1, 1), marker_time)
    if marker_dt < anchor_dt:
        marker_dt += timedelta(days=1)  # marker logged just after local midnight
    return (marker_dt - anchor_dt).total_seconds()


def trim_video(ffmpeg_path: str, video_path: Path, output_path: Path, start_seconds: float) -> tuple[bool, str]:
    """Fast, lossless trim (stream copy, snapped to the nearest keyframe --
    may land a second or two early, which is fine for cutting lead-in)."""
    cmd = [
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(start_seconds), "-i", str(video_path), "-c", "copy",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    ok = result.returncode == 0 and output_path.exists()
    return ok, (result.stderr.strip()[-800:] if not ok else "ok")


def maybe_trim(ffmpeg_path: str, video_path: Path, tmp_dir: Path, trigger: str = DEFAULT_TRIGGER) -> tuple[Path, str]:
    """The all-in-one entry point used by the pipeline. Always returns a
    usable video path -- either a freshly trimmed temp file, or the
    original video_path unchanged, along with a human-readable status
    message explaining what happened (or didn't, and why)."""
    chat_path = find_chat_file(video_path)
    if chat_path is None:
        return video_path, "no companion chat log found -- using video as-is"

    marker_time, marker_lineno, line_text = find_trigger_time(chat_path, trigger)
    if marker_time is None:
        return video_path, f"chat log '{chat_path.name}' found but '{trigger}' not in it -- using video as-is"

    anchor_time, anchor_lineno = find_first_timestamp(chat_path)
    if anchor_time is None:
        return video_path, (
            f"found '{trigger}' in '{chat_path.name}' but couldn't read a timestamp "
            f"anywhere in it -- using video as-is"
        )

    offset = compute_offset_seconds(anchor_time, marker_time)
    if offset <= 0:
        return video_path, (
            f"calculated trim offset was {offset:.1f}s (marker at line {marker_lineno} isn't "
            f"after the chat log's first line, line {anchor_lineno}) -- using video as-is"
        )

    trimmed_path = tmp_dir / f"{video_path.stem}_trimmed{video_path.suffix}"
    ok, msg = trim_video(ffmpeg_path, video_path, trimmed_path, offset)
    if not ok:
        return video_path, f"trim ffmpeg command failed ({msg}) -- using original video as-is"

    offset_fmt = str(timedelta(seconds=int(offset)))
    return trimmed_path, (
        f"trimmed {offset_fmt} of lead-in using '{chat_path.name}' "
        f"(marker '{trigger}' at line {marker_lineno}, {anchor_time.strftime('%H:%M:%S')} "
        f"at chat log's first line {anchor_lineno} used as the recording-start anchor)"
    )
