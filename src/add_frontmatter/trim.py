"""Auto-trim a Zoom recording's lead-in using a chat-log marker.

Ported from the standalone trim_zoom.py prototype into a library used as an
automatic first stage of process_video(): if a companion chat log is found
next to a video and it contains the trigger phrase (default "!START"), the
video is losslessly trimmed to start right at that marker before frontmatter
is prepended. If no chat log is found (or the marker isn't in it), the video
is passed through untouched -- so this is purely additive for anyone not
using the marker convention.

Video-start-time detection, in order of preference:
  1. Zoom's own GMT timestamp embedded in the video's *filename* itself
     (e.g. "GMT20231018-225042_Recording_1920x1080.mp4" -> 2023-10-18
     22:50:42 UTC). This is how Zoom names cloud-recording downloads, and
     it survives a webmaster/colleague appending a resolution suffix or
     renaming the file's tail end, since only the leading GMT... token is
     needed. This is tried first because it's the most robust: it doesn't
     depend on the file still sitting in whatever folder Zoom originally
     created, unlike strategy 2.
  2. Zoom's local-recording folder-naming convention (the folder is named
     "YYYY-MM-DD HH.MM.SS Meeting Name") -- what the original trim_zoom.py
     prototype relied on exclusively.
  3. The video's own embedded creation_time metadata (via ffprobe/ffmpeg),
     as a last resort -- least reliable once a file has been re-encoded,
     re-uploaded, or otherwise touched by anything other than Zoom itself.

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

import json
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path

DEFAULT_TRIGGER = "!START"

GMT_FILENAME_RE = re.compile(r"GMT(\d{8})-(\d{6})")
FOLDER_TIMESTAMP_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{2})\.(\d{2})\.(\d{2})")
LINE_TIMESTAMP_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})")


def _video_start_from_filename(video_path: Path) -> datetime | None:
    """Strategy 1: parse Zoom's own GMT timestamp out of the filename."""
    match = GMT_FILENAME_RE.search(video_path.name)
    if not match:
        return None
    date_part, time_part = match.groups()
    try:
        return datetime.strptime(f"{date_part} {time_part}", "%Y%m%d %H%M%S")
    except ValueError:
        return None


def _video_start_from_folder_name(video_path: Path) -> datetime | None:
    """Strategy 2: Zoom's local-recording folder naming convention."""
    match = FOLDER_TIMESTAMP_RE.search(video_path.parent.name)
    if not match:
        return None
    date_part, h, m, s = match.groups()
    try:
        return datetime.strptime(f"{date_part} {h}:{m}:{s}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _video_start_from_metadata(ffmpeg_path: str, video_path: Path) -> datetime | None:
    """Strategy 3: the video's own embedded creation_time (least reliable)."""
    cmd = [
        ffmpeg_path, "-hide_banner", "-i", str(video_path),
        "-f", "ffmetadata", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    m = re.search(r"creation_time=(\S+)", result.stdout or result.stderr)
    if not m:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def find_video_start_time(ffmpeg_path: str, video_path: Path) -> tuple[datetime | None, str]:
    """Returns (start_datetime_or_None, which_strategy_worked)."""
    dt = _video_start_from_filename(video_path)
    if dt is not None:
        return dt, "filename's GMT timestamp"
    dt = _video_start_from_folder_name(video_path)
    if dt is not None:
        return dt, "containing folder's Zoom-style name"
    dt = _video_start_from_metadata(ffmpeg_path, video_path)
    if dt is not None:
        return dt, "video's embedded creation_time metadata"
    return None, "none of the available strategies matched"


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


def find_trigger_time(chat_path: Path, trigger: str) -> tuple[dt_time | None, int, str]:
    """Returns (time_or_None, line_number, matched_line_text). Uses the
    FIRST occurrence if the trigger appears more than once (e.g. someone
    tested it, then said it again for real -- the earlier one wins, same
    as the original trim_zoom.py prototype's behavior)."""
    with open(chat_path, "r", encoding="utf-8", errors="ignore") as f:
        for lineno, line in enumerate(f, start=1):
            if trigger.lower() in line.lower():
                m = LINE_TIMESTAMP_RE.match(line.strip())
                if m:
                    h, mn, s = m.groups()
                    return dt_time(int(h), int(mn), int(s)), lineno, line.strip()
    return None, 0, ""


def compute_offset_seconds(video_start: datetime, marker_time: dt_time) -> float:
    vid_today = datetime.combine(video_start.date(), video_start.time())
    marker_today = datetime.combine(video_start.date(), marker_time)
    if marker_today < vid_today:
        marker_today += timedelta(days=1)
    return (marker_today - vid_today).total_seconds()


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

    marker_time, lineno, line_text = find_trigger_time(chat_path, trigger)
    if marker_time is None:
        return video_path, f"chat log '{chat_path.name}' found but '{trigger}' not in it -- using video as-is"

    video_start, strategy = find_video_start_time(ffmpeg_path, video_path)
    if video_start is None:
        return video_path, (
            f"found '{trigger}' in '{chat_path.name}' but couldn't determine the "
            f"video's start time ({strategy}) -- using video as-is"
        )

    offset = compute_offset_seconds(video_start, marker_time)
    if offset <= 0:
        return video_path, (
            f"calculated trim offset was {offset:.1f}s (marker before detected video "
            f"start via {strategy}) -- using video as-is"
        )

    trimmed_path = tmp_dir / f"{video_path.stem}_trimmed{video_path.suffix}"
    ok, msg = trim_video(ffmpeg_path, video_path, trimmed_path, offset)
    if not ok:
        return video_path, f"trim ffmpeg command failed ({msg}) -- using original video as-is"

    offset_fmt = str(timedelta(seconds=int(offset)))
    return trimmed_path, (
        f"trimmed {offset_fmt} of lead-in using '{chat_path.name}' "
        f"(marker '{trigger}' at line {lineno}, video start via {strategy})"
    )
