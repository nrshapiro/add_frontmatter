"""Command-line interface for add_frontmatter."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .config import CONFIG_FILE, load_config, run_configure
from .core import (
    FfmpegNotFoundError, already_processed, find_target_mp4s, get_ffmpeg_path, process_video,
)
from .trim import DEFAULT_TRIGGER, maybe_trim

# These are Neil's own personal defaults for the SPS videos — anyone else
# running this tool should run `add-frontmatter --configure` once instead
# of relying on these, or pass --target/--frontmatter explicitly.
DEFAULT_TARGET = r"D:\usr6\spsvideos\for_append"
DEFAULT_FRONTMATTER = r"D:\usr6\spsvideos\for_append\frontmatter\New_SPS_Opening_2022.1.mp4"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="add-frontmatter",
        description="Prepend a frontmatter MP4 onto every MP4 in a folder.",
    )
    ap.add_argument(
        "--configure", action="store_true",
        help="Run one-time interactive setup to save your own default folders, then exit.",
    )
    ap.add_argument(
        "--target", default=None,
        help="Folder of MP4s to process. Defaults to your saved config (see --configure), "
             "else Neil's personal default.",
    )
    ap.add_argument(
        "--frontmatter", default=None,
        help="MP4 to prepend to each file. Defaults to your saved config, else Neil's personal default.",
    )
    ap.add_argument(
        "--output-dir", default=None,
        help="Where to save results. Defaults to your saved config, else <target>\\output.",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Process only the first file (a real ffmpeg run, not a simulation) so you can "
             "check the result before running the whole folder.",
    )
    ap.add_argument(
        "--no-trim", action="store_true",
        help="Skip the automatic lead-in trim even if a companion Zoom chat log with the "
             f"'{DEFAULT_TRIGGER}' marker is found next to a video.",
    )
    ap.add_argument(
        "--trigger", default=DEFAULT_TRIGGER,
        help=f"Chat marker phrase that marks where the real content begins (default: {DEFAULT_TRIGGER}).",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.configure:
        run_configure()
        return 0

    cfg = load_config()

    # Precedence: command-line flag > saved config > hardcoded default.
    used_saved_target = args.target is None and bool(cfg.get("target"))
    used_saved_frontmatter = args.frontmatter is None and bool(cfg.get("frontmatter"))

    target_dir = Path(args.target or cfg.get("target") or DEFAULT_TARGET)
    frontmatter = Path(args.frontmatter or cfg.get("frontmatter") or DEFAULT_FRONTMATTER)

    if args.output_dir:
        output_dir = Path(args.output_dir)
    elif cfg.get("output_dir"):
        output_dir = Path(cfg["output_dir"])
    else:
        output_dir = target_dir / "output"

    if not target_dir.is_dir():
        print(f"ERROR: target folder not found: {target_dir}", file=sys.stderr)
        if not cfg:
            print(
                "No saved defaults found either — run 'add-frontmatter --configure' "
                "to set up your own folders.",
                file=sys.stderr,
            )
        return 1
    if not frontmatter.is_file():
        print(f"ERROR: frontmatter file not found: {frontmatter}", file=sys.stderr)
        return 1

    videos = find_target_mp4s(target_dir, frontmatter, output_dir)
    if not videos:
        print("No MP4 files to process (folder empty, or all already have the suffix).")
        return 0

    if used_saved_target or used_saved_frontmatter:
        print(f"(using your saved defaults from {CONFIG_FILE} — run --configure to change them)")
    print(f"Frontmatter: {frontmatter}")
    print(f"Target folder: {target_dir}")
    print(f"Output folder: {output_dir}")
    print(f"Found {len(videos)} file(s) to process:\n  " + "\n  ".join(v.name for v in videos))

    try:
        ffmpeg_path = get_ffmpeg_path()
    except FfmpegNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    ok_count = 0
    skipped = []
    failed = []
    for video in videos:
        existing = already_processed(video, output_dir)
        if existing is not None:
            print(f"\nSkipping: {video.name} (already processed -> {existing.name})")
            skipped.append(video.name)
            continue

        print(f"\nProcessing: {video.name}")
        with tempfile.TemporaryDirectory() as tmp:
            if args.no_trim:
                working_video, trim_msg = video, "trimming disabled (--no-trim)"
            else:
                working_video, trim_msg = maybe_trim(ffmpeg_path, video, Path(tmp), args.trigger)
            print(f"    trim: {trim_msg}")

            success, message = process_video(
                ffmpeg_path, frontmatter, working_video, output_dir, output_name_stem=video.stem
            )
        if success:
            print(f"    done: {message}")
            ok_count += 1
        else:
            print(f"    FAILED: {message}")
            failed.append(video.name)

        if args.dry_run:
            print("\n--dry-run: only the first file was processed.")
            break

    print(f"\nDone. {ok_count} succeeded, {len(skipped)} skipped (already processed), {len(failed)} failed.")
    if failed:
        print("Failed files:\n  " + "\n  ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
