"""Core logic for prepending a frontmatter MP4 onto a folder of MP4s via ffmpeg.

Uses the `imageio-ffmpeg` package, which downloads and caches a portable
ffmpeg binary automatically on first use — no separate ffmpeg install needed.

Design: the main (submission) video's PICTURE is never re-encoded — it's
stream-copied byte-for-byte, both when joined to the frontmatter's video and
in the final output. Only the frontmatter's video is re-encoded, to match the
main video's resolution, frame rate, and pixel format exactly.

Audio is handled separately from video on purpose. Feeding a freshly
re-encoded frontmatter audio segment into the plain concat demuxer alongside
video looks fine, but isn't: AAC always pads to whole 1024-sample encoder
frames, so no amount of trimming makes a fresh AAC segment's *encoded*
duration match the video's duration to the millisecond — the result is a
small but audible sync drift at the seam (and for the rest of the file). The
fix is to build one continuous audio track with sample-accurate filtering
(which works on decoded PCM, not encoded frames) referenced against the
video's *measured* exact duration, then mux that against the untouched video.
This does mean the main video's AUDIO is re-encoded (though its picture is
not) — that's the necessary trade-off for guaranteed sync.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

SUFFIX = "with_frontmatter"

# Common audio channel-layout names -> channel count.
_CHANNEL_COUNTS = {
    "mono": 1,
    "stereo": 2,
    "2.1": 3,
    "5.1": 6,
    "5.1(side)": 6,
    "7.1": 8,
}


class FfmpegNotFoundError(RuntimeError):
    pass


def _bundled_ffmpeg_path() -> Path | None:
    """If running as a PyInstaller --onefile exe that had an ffmpeg binary
    bundled into it at build time (see .github/workflows/build.yml), return
    its path. Returns None for a normal `pip`/source run, or a build that
    didn't bundle one — get_ffmpeg_path() falls back to imageio-ffmpeg
    either way.

    Matched by a "ffmpeg*" prefix rather than an exact "ffmpeg"/"ffmpeg.exe"
    name: PyInstaller's --add-binary preserves the source file's own
    filename rather than renaming it, and imageio-ffmpeg's cached binaries
    are versioned (e.g. "ffmpeg-linux-x86_64-v7.0.2", "ffmpeg-win64-v4.2.2.exe")
    -- an exact-name check never matches those and silently falls through to
    the imageio-ffmpeg download path every time, even in a build that did
    bundle one."""
    import sys
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    candidates = sorted(
        p for p in Path(meipass).glob("ffmpeg*")
        if p.is_file() and p.suffix.lower() not in (".txt", ".toc", ".py")
    )
    return candidates[0] if candidates else None


def get_ffmpeg_path() -> str:
    """Return the path to a working ffmpeg binary. Prefers one bundled
    directly into a PyInstaller exe build (no internet needed at all);
    otherwise falls back to imageio-ffmpeg, which downloads and caches a
    portable ffmpeg binary on first use."""
    bundled = _bundled_ffmpeg_path()
    if bundled is not None:
        return str(bundled)

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # download failure, unsupported platform, etc.
        raise FfmpegNotFoundError(
            "Could not obtain an ffmpeg binary via imageio-ffmpeg "
            "(this needs an internet connection the first time it runs). "
            f"Original error: {exc}"
        ) from exc


def find_target_mp4s(target_dir: Path, frontmatter_path: Path, output_dir: Path) -> list[Path]:
    """MP4s directly in target_dir, excluding the frontmatter file, anything
    already in output_dir, and anything already carrying the suffix."""
    results = []
    for p in sorted(target_dir.glob("*.mp4")):
        if p.resolve() == frontmatter_path.resolve():
            continue
        if output_dir.resolve() != target_dir.resolve() and p.parent.resolve() == output_dir.resolve():
            continue
        if p.stem.endswith(f"_{SUFFIX}"):
            continue
        results.append(p)
    return results


def probe_streams(ffmpeg_path: str, path: Path) -> dict:
    """Best-effort probe of stream info by parsing ffmpeg's own -i output
    (no ffprobe needed, since imageio-ffmpeg only bundles ffmpeg itself)."""
    result = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-i", str(path)],
        capture_output=True, text=True,
    )
    text = result.stderr
    info = {
        "width": None, "height": None, "fps": None, "pix_fmt": None, "video_codec": None, "tbn": None,
        "has_audio": False, "audio_codec": None, "sample_rate": None, "channels": None,
        "duration": None,
    }

    m_dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m_dur:
        h, mnt, s = m_dur.groups()
        info["duration"] = int(h) * 3600 + int(mnt) * 60 + float(s)

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Stream") and "Video:" in line:
            m_codec = re.search(r"Video:\s*([a-zA-Z0-9_]+)", line)
            if m_codec:
                info["video_codec"] = m_codec.group(1).lower()
            m_res = re.search(r"(\d{2,5})x(\d{2,5})", line)
            if m_res:
                info["width"], info["height"] = int(m_res.group(1)), int(m_res.group(2))
            m_pix = re.search(r",\s*([a-z0-9]+)(?:\([^)]*\))?,\s*\d+x\d+", line)
            if m_pix:
                info["pix_fmt"] = m_pix.group(1)
            m_fps = re.search(r"([\d.]+)\s+fps", line)
            if m_fps:
                try:
                    info["fps"] = float(m_fps.group(1))
                except ValueError:
                    pass
            m_tbn = re.search(r"([\d.]+)k?\s+tbn", line)
            if m_tbn:
                try:
                    raw = m_tbn.group(1)
                    value = float(raw) * (1000 if "k" in line[m_tbn.start():m_tbn.end()] else 1)
                    info["tbn"] = int(round(value))
                except ValueError:
                    pass
        if line.startswith("Stream") and "Audio:" in line:
            info["has_audio"] = True
            m_acodec = re.search(r"Audio:\s*([a-zA-Z0-9_]+)", line)
            if m_acodec:
                info["audio_codec"] = m_acodec.group(1).lower()
            m_rate = re.search(r"(\d+)\s*Hz", line)
            if m_rate:
                info["sample_rate"] = int(m_rate.group(1))
            m_layout = re.search(r"Hz,\s*([^,]+),", line)
            if m_layout:
                layout = m_layout.group(1).strip()
                info["channels"] = _CHANNEL_COUNTS.get(layout, 2)

    return info


def _video_encoder_for(codec: str | None) -> str:
    codec = (codec or "").lower()
    if codec in ("hevc", "h265"):
        return "libx265"
    return "libx264"  # safe default for consumer camera footage (h264 or unrecognized)


def _decoded_frame_count(ffmpeg_path: str, path: Path, stream: str = "0:v") -> int | None:
    """Exact frame count via a full decode pass (more reliable than parsing
    container metadata, which can be imprecise or reflect edit lists).

    ffmpeg writes a running "frame=   N" progress update to stderr many times
    throughout decoding (not just once at the end), so this must take the
    LAST occurrence — the final total — not the first, which would badly
    undercount and was an earlier bug here (e.g. reporting ~100 frames of
    real footage that actually had over 1000)."""
    result = subprocess.run(
        [ffmpeg_path, "-i", str(path), "-map", stream, "-f", "null", "-", "-hide_banner"],
        capture_output=True, text=True,
    )
    matches = re.findall(r"frame=\s*(\d+)", result.stderr)
    return int(matches[-1]) if matches else None


def conform_frontmatter_video(ffmpeg_path: str, frontmatter: Path, target: dict, tmp_dir: Path) -> tuple[Path | None, float, str]:
    """Re-encode just the frontmatter's video to match the main video's
    resolution, frame rate, and pixel format. No audio here — audio is built
    separately for sample-accurate sync (see module docstring).
    Returns (path_or_None, precise_duration_seconds, message_or_error)."""
    width = target["width"] or 1920
    height = target["height"] or 1080
    fps = target["fps"] or 30
    pix_fmt = target["pix_fmt"] or "yuv420p"
    vcodec = _video_encoder_for(target["video_codec"])

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format={pix_fmt}"
    )

    out = tmp_dir / "frontmatter_video_only.mp4"
    cmd = [
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", "-fflags", "+genpts",
        "-i", str(frontmatter),
        "-vf", vf, "-fps_mode", "cfr", "-c:v", vcodec, "-crf", "18", "-preset", "medium", "-bf", "0",
        "-avoid_negative_ts", "make_zero",
    ]
    # Match the main video's own timebase exactly. The concat demuxer used
    # later doesn't reliably rescale timestamps between files with different
    # timebases — a mismatch here (e.g. our re-encode defaulting to some
    # other timescale than the main video's native one) causes the main
    # video's portion to be spliced in at a wildly wrong timestamp, seen as
    # the picture jumping to the wrong point in time by many seconds, not a
    # subtle sync error.
    if target["tbn"]:
        cmd += ["-video_track_timescale", str(target["tbn"])]
    cmd += ["-an", str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not out.exists():
        return None, 0.0, result.stderr.strip()[-800:] or "ffmpeg failed to encode frontmatter video"

    frame_count = _decoded_frame_count(ffmpeg_path, out)
    if not frame_count:
        return None, 0.0, "could not determine conformed frontmatter's frame count"
    precise_duration = frame_count / fps  # exact, by construction of CFR encoding above
    return out, precise_duration, "ok"


def _extract_video_only(ffmpeg_path: str, video: Path, out_path: Path) -> tuple[bool, str]:
    """Stream-copy just the video track out of a file — byte-identical
    picture, just dropping any audio stream so it matches the frontmatter's
    video-only layout for the concat demuxer (see concat_video_only)."""
    cmd = [
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-map", "0:v:0", "-c:v", "copy", "-an", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    ok = result.returncode == 0 and out_path.exists()
    return ok, result.stderr.strip()[-800:] if not ok else "ok"


def concat_video_only(ffmpeg_path: str, frontmatter_video: Path, video: Path, out_path: Path, list_file: Path, tmp_dir: Path) -> tuple[bool, str]:
    """Stream-copy concat of just the two video tracks — no audio involved,
    so this is straightforward and frame-accurate. Main video's picture
    passes through untouched.

    The concat *demuxer* requires every listed file to have the same stream
    layout. frontmatter_video is video-only (1 stream); if the main video
    file still has its own audio stream (2 streams) when handed to the
    demuxer directly, that layout mismatch corrupts the splice — packets get
    misattributed and the second file's timestamps come out wildly wrong
    (seen as the main video's picture jumping to the wrong point in time,
    tens of seconds off, not just a few milliseconds). So the main video is
    first stream-copied into its own video-only file — same picture, byte
    for byte, just matching layout — before the two are concatenated."""
    main_video_only = tmp_dir / "main_video_only.mp4"
    ok, msg = _extract_video_only(ffmpeg_path, video, main_video_only)
    if not ok:
        return False, f"failed to extract main video's picture: {msg}"

    list_file.write_text(
        f"file '{frontmatter_video.as_posix()}'\nfile '{main_video_only.as_posix()}'\n",
        encoding="utf-8",
    )
    cmd = [
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-map", "0:v:0", "-c:v", "copy", "-an", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    ok = result.returncode == 0 and out_path.exists()
    return ok, result.stderr.strip()[-800:] if not ok else "ok"


def build_audio_track(
    ffmpeg_path: str, frontmatter: Path, fm_precise_duration: float, video: Path, target: dict, tmp_dir: Path
) -> tuple[Path | None, str]:
    """Build one continuous, sample-accurate audio track: frontmatter's audio
    (or generated silence, trimmed exactly to the conformed frontmatter
    video's measured duration) followed by the main video's own original
    audio in full. Uses the concat *filter* (decoded samples), not the
    demuxer, so there's no AAC frame-boundary quantization at the seam."""
    fm_info = probe_streams(ffmpeg_path, frontmatter)
    sample_rate = target["sample_rate"] or 48000
    channels = target["channels"] or 2
    out = tmp_dir / "audio_track.m4a"

    if fm_info["has_audio"]:
        inputs = ["-i", str(frontmatter), "-i", str(video)]
        fm_chain = (
            f"[0:a]atrim=0:{fm_precise_duration:.6f},asetpts=PTS-STARTPTS,"
            f"aresample=async=1:first_pts=0,aformat=sample_rates={sample_rate}[a0]"
        )
        main_idx = 1
    else:
        layout = "stereo" if channels == 2 else "mono" if channels == 1 else f"{channels}c"
        inputs = ["-i", str(video), "-f", "lavfi", "-i", f"anullsrc=r={sample_rate}:cl={layout}"]
        fm_chain = (
            f"[1:a]atrim=0:{fm_precise_duration:.6f},asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates={sample_rate}[a0]"
        )
        main_idx = 0

    main_chain = f"[{main_idx}:a]aformat=sample_rates={sample_rate},asetpts=PTS-STARTPTS[a1]"
    concat_chain = "[a0][a1]concat=n=2:v=0:a=1[outa]"
    filter_complex = ";".join([fm_chain, main_chain, concat_chain])

    cmd = [
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outa]", "-c:a", "aac", "-ar", str(sample_rate), "-ac", str(channels),
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and out.exists():
        return out, "ok"
    return None, result.stderr.strip()[-800:] or "ffmpeg failed to build the combined audio track"


def mux_video_and_audio(ffmpeg_path: str, video_path: Path, audio_path: Path | None, out_path: Path) -> tuple[bool, str]:
    """Combine the (untouched, stream-copied) combined video with the
    (freshly built) combined audio into the final output. If audio_path is
    None, the output is video-only (matches the main video having no audio)."""
    if audio_path is None:
        cmd = [
            ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path), "-map", "0:v", "-c:v", "copy", str(out_path),
        ]
    else:
        cmd = [
            ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path), "-i", str(audio_path),
            "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "copy",
            str(out_path),
        ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    ok = result.returncode == 0 and out_path.exists()
    return ok, result.stderr.strip()[-800:] if not ok else "ok"


def process_video(ffmpeg_path: str, frontmatter: Path, video: Path, output_dir: Path) -> tuple[bool, str]:
    """Process a single video. The main video's picture is stream-copied
    (byte-identical, never re-encoded) both at the video-concat step and in
    the final mux. Audio is rebuilt from scratch with sample-accurate
    filtering to guarantee sync at the seam — see module docstring for why
    that's necessary. Returns (success, message)."""
    out_name = f"{video.stem}_{SUFFIX}{video.suffix}"
    out_path = output_dir / out_name

    target = probe_streams(ffmpeg_path, video)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        fm_video, fm_duration, msg = conform_frontmatter_video(ffmpeg_path, frontmatter, target, tmp_dir)
        if fm_video is None:
            return False, f"failed to conform frontmatter video: {msg}"

        combined_video = tmp_dir / "combined_video.mp4"
        list_file = tmp_dir / "concat_list.txt"
        ok, msg = concat_video_only(ffmpeg_path, fm_video, video, combined_video, list_file, tmp_dir)
        if not ok:
            return False, f"video concat failed: {msg}"

        if not target["has_audio"]:
            ok, msg = mux_video_and_audio(ffmpeg_path, combined_video, None, out_path)
            if ok:
                return True, f"{out_name} (main video's picture untouched; no audio in source)"
            return False, f"final mux failed: {msg}"

        audio_track, msg = build_audio_track(ffmpeg_path, frontmatter, fm_duration, video, target, tmp_dir)
        if audio_track is None:
            return False, f"failed to build audio track: {msg}"

        ok, msg = mux_video_and_audio(ffmpeg_path, combined_video, audio_track, out_path)
        if ok:
            return True, f"{out_name} (main video's picture untouched; audio rebuilt for sync)"
        return False, f"final mux failed: {msg}"
