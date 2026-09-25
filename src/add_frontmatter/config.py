"""Per-user config file for add_frontmatter.

Lets each person running this tool save their own default folders (target,
frontmatter, output) once, instead of typing --target/--frontmatter on every
run. Precedence is: command-line flags > saved config > the built-in
defaults in cli.py (which are specific to the original SPS video setup).
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".add_frontmatter"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict:
    """Return the saved config as a dict, or {} if none exists yet or it's
    unreadable (never raises — a bad config file should just be ignored,
    not crash the program)."""
    if not CONFIG_FILE.is_file():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(target: str, frontmatter: str, output_dir: str | None) -> Path:
    """Save the given values as this user's defaults. Returns the config path."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {"target": target, "frontmatter": frontmatter, "output_dir": output_dir}
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return CONFIG_FILE


def _prompt_path(label: str, must_exist_as: str, current: str | None = None) -> str:
    """Ask for a path, stripping stray quotes (common when dragging a
    folder/file into the terminal instead of typing it), and keep asking
    until it actually exists.

    If `current` is given and is still a valid path of the right kind, it's
    shown in [brackets] and pressing Enter keeps it. If `current` is no
    longer valid (moved/deleted), it's not offered as a default -- you have
    to type a real path, same as first-time setup."""
    current_is_valid = bool(current) and (
        (must_exist_as == "dir" and Path(current).is_dir())
        or (must_exist_as == "file" and Path(current).is_file())
    )
    suffix = f" [{current}]" if current_is_valid else ""
    while True:
        raw = input(f"{label}{suffix}: ").strip().strip('"').strip("'")
        if not raw and current_is_valid:
            return current
        p = Path(raw)
        if must_exist_as == "dir" and p.is_dir():
            return raw
        if must_exist_as == "file" and p.is_file():
            return raw
        print(f"  Can't find that {must_exist_as} — please try again (or Ctrl+C to cancel).")


def run_configure() -> None:
    """Interactive setup wizard: asks for this user's own folders and saves
    them so future runs need no flags at all. Re-running this later shows
    whatever's currently saved as the default (Enter keeps it), so you can
    tweak just one value without retyping the others."""
    print("Let's set up your defaults for add-frontmatter.")
    print("(Tip: you can drag a folder or file into this window instead of typing the path.)\n")

    current = load_config()
    if current:
        print("Current values are shown in [brackets] -- press Enter to keep one as-is.\n")

    target = _prompt_path(
        "Folder containing the MP4 files to process", "dir", current.get("target")
    )
    frontmatter = _prompt_path(
        "Path to the frontmatter MP4 to prepend", "file", current.get("frontmatter")
    )

    current_output = current.get("output_dir")
    output_suffix = f" [{current_output}]" if current_output else " [output subfolder]"
    output_raw = input(f"Output folder{output_suffix}: ").strip().strip('"').strip("'")
    output_dir = output_raw or current_output or None

    path = save_config(target, frontmatter, output_dir)
    print(f"\nSaved to {path}")
    print("From now on you can just run:  add-frontmatter --dry-run")
    print("(then, once that looks right:  add-frontmatter)")
    print("\nRun 'add-frontmatter --configure' again any time to change these.")
