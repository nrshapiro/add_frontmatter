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

Computing the trim offset means comparing two clocks: the chat log's
wall-clock time, and *some* notion of when the video itself started. Two
approaches were tried and both had a real flaw, in opposite directions:

  - Comparing against the video's Zoom-assigned GMT filename prefix
    directly (an earlier version of this file): that prefix is UTC, while
    the chat log's wall-clock timestamps are the meeting host's LOCAL
    time -- comparing them raw silently introduces a fixed multi-hour
    error (whatever the local UTC offset is).
  - Anchoring entirely within the chat log itself -- using its own FIRST
    line as a stand-in for "recording start" (a later version of this
    file, after the above bug): time zone-safe, but systematically
    UNDER-trims by however long it took someone to type the first chat
    message after the host actually clicked Record -- commonly tens of
    seconds, confirmed in testing (a real recording left ~19s of
    unwanted lead-in with this approach).

The fix used here: convert the video's own GMT filename timestamp (an
authoritative, to-the-second UTC record of when Zoom actually started
recording -- the most accurate source available) into the meeting's local
time zone, and compare THAT against the chat log's wall-clock marker. This
club's meetings are always run from the Eastern time zone, so that
conversion uses the "America/New_York" IANA zone (which correctly accounts
for EST/EDT across the year) -- hardcoded here the same way this whole
tool already hardcodes a set of default folder paths; not a general
solution for a differently-located user, but correct for this one.
Falls back to anchoring on the chat log's own first line (the previous,
less-accurate approach) only when the video's filename has no GMT prefix
to convert -- e.g. it's a local (not cloud) Zoom recording.

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

Manual override: renaming a video to include "-StartOffsetMMSS" (e.g.
"-StartOffset0342" for 3 minutes 42 seconds) overrides all of the above --
no chat log is even looked for. This exists for when the auto-detected trim
turns out to be a few seconds off: rather than editing anything, just rename
the file with a corrected offset and run again ("StartOffset0000" means
"don't trim this one at all"). Deliberately a fixed 4-digit MM SS format,
not also accepting some longer HHMMSS form for very long offsets -- the
lead-in this tool trims is always a few minutes at most, so 99:59 of
headroom is more than this will ever need, and one unambiguous width is
simpler than two.

The effective trim offset actually used -- whether from this override or
from auto-detection -- is echoed back in the OUTPUT filename too (see
core.py), using this exact same "StartOffsetMMSS" spelling, so nudging it
after the fact is a copy/paste, not a lookup.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta, time as dt_time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_TRIGGER = "!START"

# This tool is built for one specific group's recurring meetings, all run
# from the same time zone -- so hardcoding the meeting's time zone here
# follows the same pattern already established elsewhere in this codebase
# (see cli.py's own hardcoded default folder paths).
MEETING_TIMEZONE = ZoneInfo("America/New_York")

GMT_FILENAME_RE = re.compile(r"GMT(\d{8})-(\d{6})")
LINE_TIMESTAMP_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})")

# The manual override token, e.g. "-StartOffset0342". Case-insensitive (a
# person retyping this by hand may not match the exact case), and matched
# anywhere in the filename rather than requiring the leading "-" -- the
# separator is just a readability convention, not something to enforce.
OFFSET_TOKEN_RE = re.compile(r"StartOffset(\d{2})(\d{2})", re.IGNORECASE)


def override_offset_seconds(video_path: Path) -> int | None:
    """The manual override offset (in seconds) encoded in the video's own
    filename, or None if it doesn't have one. See module docstring."""
    match = OFFSET_TOKEN_RE.search(video_path.stem)
    if not match:
        return None
    minutes, seconds = match.groups()
    return int(minutes) * 60 + int(seconds)


def format_offset_token(seconds: float) -> str:
    """The reverse of override_offset_seconds: turns an effective offset
    back into the same "MMSS" spelling, for tagging onto the output
    filename (see core.py). Rounds to the nearest whole second -- the
    trim itself is keyframe-snapped anyway, so sub-second precision in the
    displayed offset would be false precision."""
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}{secs:02d}"


# Matches the override token together with a leading separator, if any, so
# it can be cleanly removed rather than just zeroed out in place.
_OVERRIDE_TOKEN_STRIP_RE = re.compile(r"[-_]?StartOffset\d{4}", re.IGNORECASE)


def strip_offset_token(name: str) -> str:
    """Removes a manual "-StartOffsetMMSS" override token from a filename
    stem, e.g. when building an output filename from a source stem that may
    carry one -- otherwise it would end up duplicated alongside the
    "_StartOffsetMMSS" tag core.py adds to report the offset actually
    used, which may not even be the same number (a person can, and often
    will, nudge it a little from what they first tried)."""
    return _OVERRIDE_TOKEN_STRIP_RE.sub("", name)


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


def video_start_local_time(video_path: Path) -> dt_time | None:
    """Zoom's own GMT<date>-<time> timestamp in the video's filename,
    converted from UTC to this club's meeting time zone -- the accurate
    source of "when did recording actually start," in the same wall-clock
    terms as the chat log. Returns None if the filename has no such prefix
    (e.g. a local, non-cloud recording, or a file renamed beyond recognition)."""
    match = GMT_FILENAME_RE.search(video_path.name)
    if not match:
        return None
    date_part, time_part = match.groups()
    try:
        utc_dt = datetime.strptime(f"{date_part} {time_part}", "%Y%m%d %H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return utc_dt.astimezone(MEETING_TIMEZONE).time()


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


def maybe_trim(
    ffmpeg_path: str, video_path: Path, tmp_dir: Path, trigger: str = DEFAULT_TRIGGER,
) -> tuple[Path, str, float | None]:
    """The all-in-one entry point used by the pipeline. Always returns
    (working_video_path, message, effective_offset_seconds):
      - working_video_path is either a freshly trimmed temp file, or the
        original video_path unchanged.
      - message is a human-readable explanation of what happened (or
        didn't, and why).
      - effective_offset_seconds is the offset actually trimmed, for the
        caller to tag onto the output filename (see core.py) -- or None
        when no trim was applied, so the caller can leave that tag off
        entirely.

    A manual "-StartOffsetMMSS" override in video_path's own filename takes
    priority over everything else here -- no chat log is even looked for
    in that case. See the module docstring for why."""
    override = override_offset_seconds(video_path)
    if override is not None:
        if override <= 0:
            return video_path, (
                f"'{video_path.name}' has a StartOffset{format_offset_token(override)} override "
                f"requesting no trim -- using video as-is"
            ), None
        trimmed_path = tmp_dir / f"{video_path.stem}_trimmed{video_path.suffix}"
        ok, msg = trim_video(ffmpeg_path, video_path, trimmed_path, override)
        if not ok:
            return video_path, f"trim ffmpeg command failed ({msg}) -- using original video as-is", None
        offset_fmt = str(timedelta(seconds=override))
        return trimmed_path, (
            f"trimmed {offset_fmt} of lead-in per the StartOffset{format_offset_token(override)} "
            f"override in the filename"
        ), override

    chat_path = find_chat_file(video_path)
    if chat_path is None:
        return video_path, "no companion chat log found -- using video as-is", None

    marker_time, marker_lineno, line_text = find_trigger_time(chat_path, trigger)
    if marker_time is None:
        return video_path, f"chat log '{chat_path.name}' found but '{trigger}' not in it -- using video as-is", None

    filename_anchor = video_start_local_time(video_path)
    if filename_anchor is not None:
        anchor_time = filename_anchor
        anchor_desc = f"video's own GMT filename timestamp, converted to {MEETING_TIMEZONE.key}"
    else:
        anchor_time, anchor_lineno = find_first_timestamp(chat_path)
        if anchor_time is None:
            return video_path, (
                f"found '{trigger}' in '{chat_path.name}' but couldn't read a timestamp "
                f"anywhere in it, and the video's filename has no GMT prefix to fall back "
                f"on -- using video as-is"
            ), None
        anchor_desc = f"chat log's own first line (line {anchor_lineno}) -- less exact, no GMT filename to use instead"

    offset = compute_offset_seconds(anchor_time, marker_time)
    if offset <= 0:
        return video_path, (
            f"calculated trim offset was {offset:.1f}s (marker at line {marker_lineno} isn't "
            f"after the detected recording start, {anchor_time.strftime('%H:%M:%S')} via "
            f"{anchor_desc}) -- using video as-is"
        ), None

    trimmed_path = tmp_dir / f"{video_path.stem}_trimmed{video_path.suffix}"
    ok, msg = trim_video(ffmpeg_path, video_path, trimmed_path, offset)
    if not ok:
        return video_path, f"trim ffmpeg command failed ({msg}) -- using original video as-is", None

    offset_fmt = str(timedelta(seconds=int(offset)))
    return trimmed_path, (
        f"trimmed {offset_fmt} of lead-in using '{chat_path.name}' "
        f"(marker '{trigger}' at line {marker_lineno}; recording start {anchor_time.strftime('%H:%M:%S')} "
        f"via {anchor_desc}) -- rename the video with e.g. \"-StartOffset{format_offset_token(offset)}\" "
        f"and re-run to nudge this by hand"
    ), offset
