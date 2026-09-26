# add-frontmatter

Prepends a "frontmatter" MP4 (e.g. a club opening title) onto every MP4 in a
target folder. Powered by [ffmpeg](https://ffmpeg.org/) under the hood — no
separate install needed, it's bundled into every download below.

Each output file is saved as:

```
<original_stem>_with_frontmatter.mp4
```

Comes in two forms, sharing the same underlying video logic:

- **A desktop app** — double-click, choose files, click Process. No
  terminal, no Python. Available for both **Windows** and **Mac**.
- **A command-line tool** — for batch/scripted use, currently **Windows
  only**.

---

## For anyone just running this tool

### Desktop app (recommended if you're not comfortable with a terminal)

**No Python install needed.** Grab the latest build from this repo's
[Releases page](../../releases/latest) (or the **Actions** tab for the
newest build from `main`, if there isn't a tagged release yet):

- **Windows:** `Add-Frontmatter-GUI-Windows` → `Add-Frontmatter-GUI.exe`
- **Mac:** `Add-Frontmatter-GUI-macOS` → unzip it to get
  `Add-Frontmatter-GUI.app`

Double-click to open it.

- **Windows** may show a "Windows protected your PC" SmartScreen warning
  the first time — this is a well-known false positive for unsigned
  PyInstaller apps like this one, not a sign of a problem. Click **More
  info**, then **Run anyway**.
- **Mac** may say it "cannot be opened because the developer cannot be
  verified" — right-click (or Control-click) the app, choose **Open**, then
  confirm **Open** in the dialog that appears. You only need to do this
  once.

In the app: click **Choose…** next to "Frontmatter video" to point it at
your opening clip (only needs doing once — it's remembered after that),
then **Add Files…** to pick the videos you want to process, then
**Process**.

### Command line (Windows only)

**No Python install needed.** Grab `add-frontmatter.exe` from
[Releases](../../releases/latest) (or the **Actions** tab) — a single
self-contained file with everything, including ffmpeg, built in.

```
add-frontmatter --configure
```

Asks for your video folder and your frontmatter file, then remembers them
for every future run. (These are *your own* folders — the tool ships with
no useful defaults for anyone but Neil, so this step matters.)

```
add-frontmatter --dry-run
```

Check that the one output file looks right, then run the whole folder:

```
add-frontmatter
```

Run `add-frontmatter --configure` again any time to change your saved
folders, or override just this once with `--target`/`--frontmatter` flags
(see "Usage" below for the full list).

---

## For development

### Requirements

- Python 3.9+
- An internet connection the *first* time you run **from source** — see
  below. (Doesn't apply to any of the prebuilt downloads above — ffmpeg is
  already inside them.)

This project uses the [`imageio-ffmpeg`](https://github.com/imageio/imageio-ffmpeg)
package, which downloads and caches a portable ffmpeg binary automatically
the first time the tool runs from source (a one-time download of a few dozen
MB). After that first run it works fully offline.

### Install from source

```bash
pip install -e ".[dev]"
```

This installs both commands — `add-frontmatter` (CLI) and
`add-frontmatter-gui` (desktop app) — plus `pytest` and `pyinstaller` for
development/building. On Windows this may print a warning that an installed
`.exe` isn't on PATH — see Troubleshooting.

Run the GUI from source directly with:

```bash
add-frontmatter-gui
```

### Building the executables yourself

Normally you don't need to — GitHub Actions builds all three (the CLI exe,
the Windows GUI exe, and the Mac GUI app) automatically on every push to
`main`, and the results show up under the **Actions** tab (or **Releases**,
for tagged versions). Grab the build from there rather than building
locally, unless you're changing the code and need to test something.

PyInstaller only builds for the platform it runs *on* — you can't produce a
Mac `.app` from Windows or vice versa. That's exactly why the GitHub Actions
workflow (using GitHub's own Windows and Mac runners) is the practical path
for producing all three artifacts without owning both kinds of machine.

The build commands themselves (see `.github/workflows/build.yml` for the
exact, current versions):

```powershell
# CLI (Windows only) — from src/run_add_frontmatter.py, a thin wrapper
# (PyInstaller needs a plain top-level script; running cli.py directly
# would break its internal relative imports)
pyinstaller --onefile --name add-frontmatter --paths src --add-binary "<ffmpeg-path>;." src/run_add_frontmatter.py

# GUI, Windows — same wrapper idea, plus --windowed (no console window)
# and --add-data to bundle the app's icon/logo assets
pyinstaller --onefile --windowed --name Add-Frontmatter-GUI --paths src `
  --add-binary "<ffmpeg-path>;." --add-data "src/add_frontmatter/assets;add_frontmatter/assets" `
  --icon "src/add_frontmatter/assets/sps_logo.ico" src/run_add_frontmatter_gui.py

# GUI, Mac — same idea; --windowed makes PyInstaller wrap the result in a
# proper .app bundle even in --onefile mode, no separate spec-file step needed
pyinstaller --onefile --windowed --name Add-Frontmatter-GUI --paths src \
  --add-binary "<ffmpeg-path>:." --add-data "src/add_frontmatter/assets:add_frontmatter/assets" \
  --icon "src/add_frontmatter/assets/sps_logo.icns" src/run_add_frontmatter_gui.py
```

`<ffmpeg-path>` is whatever `imageio_ffmpeg.get_ffmpeg_exe()` prints (after
`pip install -e ".[dev]"`, run
`python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"`)
— this is what gets bundled directly into the executable so nobody running
it needs their own internet connection, not even on first launch.

## Usage (CLI, all flags)

```bash
add-frontmatter
```

Forgot a flag? `add-frontmatter --help` (or `-h`) prints the full list with
a description of each one.

`--target`, `--frontmatter`, and `--output-dir` can come from three places.
If you pass one on the command line, that's used. Otherwise, it falls back
to whatever you saved with `--configure`. If neither is set, it falls back
to Neil's own hardcoded folders (`D:\usr6\spsvideos\...`) — meant only for
his machine, not a useful default for anyone else.

```bash
add-frontmatter --configure                      # one-time interactive setup
add-frontmatter --target "D:\path\to\videos" --frontmatter "D:\path\to\opening.mp4"
add-frontmatter --output-dir "D:\path\to\somewhere\else"
add-frontmatter --dry-run                         # process just the first file, to check it
add-frontmatter --no-trim                         # skip auto-trim even if a chat log is found
add-frontmatter --trigger "!GO"                   # use a different chat marker than !START
```

`--dry-run` processes only the first file found — a real ffmpeg run, not a
simulation — so you can check the result before committing to the whole
folder. Files that already have a matching `_with_frontmatter` output are
skipped automatically, so rerunning after adding a few new videos only
processes what's new. See "Auto-trim details" above for `--no-trim` and
`--trigger`.

The desktop app (`add-frontmatter-gui` / the `.exe`/`.app` builds) covers
the same ground through its Settings panel and file list instead of flags —
see "Desktop app" above.

### How it works (both CLI and desktop app — same underlying code)

1. Scans the target folder for `*.mp4` files (skips the frontmatter file
   itself and anything already ending in `_with_frontmatter`). The desktop
   app instead processes whichever files you've added to its list.
2. **Already-processed files are skipped.** If `<name>_with_frontmatter.mp4`
   already exists in the output folder, that source video is skipped
   entirely rather than redone — reruns over a folder you've added a few
   new videos to only do the new ones, not a full re-encode of everything
   again.
3. **Auto-trim, if a companion Zoom chat log is found.** Before the
   frontmatter step, each video is checked for a chat-log file sitting next
   to it containing the marker phrase `!START` (typed into the meeting chat
   by whoever's hosting, right before the real content begins). If found,
   the lead-in before that marker is losslessly trimmed off first; if no
   chat log is found, or the marker isn't in it, the video is used as-is —
   this is purely additive and never blocks processing. See "Auto-trim
   details" below for exactly what's expected and how it decides.
4. **The main video's picture is never re-encoded** — it's byte-copied,
   unchanged, throughout. The tool probes the main video's exact resolution,
   frame rate, and pixel format, then re-encodes a temporary copy of the
   frontmatter's video to match precisely. The two video tracks are then
   joined with a plain stream copy.
5. Audio is built separately from video on purpose. Feeding a freshly
   re-encoded frontmatter *audio* segment into a plain stream-copy concat
   alongside video looks fine but isn't: AAC always pads to whole encoder
   frames, so a fresh segment's encoded length can't be trimmed to match the
   video to the millisecond — the result is a small but audible sync drift
   at the seam. Instead, one continuous audio track (frontmatter's audio, or
   silence if it has none, followed by the main clip's own original audio)
   is built with sample-accurate filtering referenced against the video's
   *measured* exact duration, then muxed against the untouched video. This
   is the one part of the main video file that does get re-encoded — its
   audio, not its picture — because that's what's needed to guarantee sync.
6. If the main video has no audio track at all, the output has none either.
   If the main video has audio but the frontmatter doesn't, silence matching
   the main video's audio format fills the frontmatter's portion.
7. Saves each result with the `_with_frontmatter` suffix.

### Auto-trim details

No setup needed to *use* this — if a video has a companion chat log with the
marker in it, it's trimmed automatically. What's worth knowing:

- **The marker.** Default is `!START`, typed anywhere in the meeting chat
  (case-insensitive) by whoever's hosting, right before the real content
  begins. Override it with `--trigger "!GO"` (CLI) — the desktop app always
  uses the default. If the marker appears more than once in the chat, the
  *first* occurrence is used.
- **Finding the chat log.** Any `.txt` file in the same folder as the video
  is a candidate, picked in this order: (1) one whose name shares the
  video's own `GMT<date>-<time>` prefix, if the video's filename has one —
  this is exactly how Zoom names a cloud recording's chat-log download
  alongside its video (e.g. `GMT20231018-225042_Recording.txt` next to
  `GMT20231018-225042_Recording_1920x1080.mp4`), even though that filename
  doesn't contain the word "chat" anywhere; (2) failing that, any file with
  "chat" in its name (covers Zoom's local `meeting_saved_chat.txt`); (3) if
  exactly one `.txt` file is sitting there and neither of the above matched,
  that one is used. No match found at all → trimming is skipped for that
  video, nothing else changes.
- **Computing the trim offset.** Zoom's chat-log timestamps are real
  wall-clock time-of-day (e.g. `22:35:02`, not "35 minutes into the
  meeting"). The offset is the difference between the marker's timestamp
  and the chat log's own *first* timestamped line — both read off the same
  clock, in the chat log itself. This deliberately never looks at the
  video's filename, containing folder, or embedded metadata for this: the
  video's Zoom-assigned filename timestamp is UTC, while the chat log is
  the host's local time, and cross-referencing those two clocks directly
  would silently introduce a multi-hour error. Anchoring entirely within the
  chat log sidesteps that. (The one edge case: if someone was chatting well
  before the host actually started recording, the trim will be a bit
  shorter than ideal, never longer than it should be — safe in the
  direction that matters.)
- **The trim itself** is a fast, lossless stream copy (same as the rest of
  this tool's philosophy of never re-encoding picture it doesn't have to) —
  snapped to the nearest keyframe, so it may start a second or two before
  the exact marker, which is fine for cutting lead-in buffer.
- **Turning it off:** pass `--no-trim` (CLI) or uncheck "Auto-trim…" in the
  desktop app's Settings panel (saved for next time, like the other
  settings there).

## Troubleshooting

**Windows: "The script add-frontmatter.exe is installed in ... which is not
on PATH"** (only applies when installing from source with `pip`)
The command was installed correctly, but your terminal doesn't know where to
find it yet. Add the folder named in the warning to your PATH via "Edit
environment variables for your account" in Windows search, then reopen your
terminal. Or, simpler: just use the prebuilt exe from Releases instead of
installing from source.

**"No MP4 files to process"** (CLI) / an empty file list after Process
(desktop app)
Either the target folder is genuinely empty of MP4s, or everything in it
already has the `_with_frontmatter` suffix (skipped on purpose, so reruns
don't double-process files) — CLI only; the desktop app processes exactly
the files you added regardless of suffix.

**ffmpeg-related errors on first run (source installs only)**
The very first run from source needs an internet connection to download and
cache a portable ffmpeg binary (via `imageio-ffmpeg`). After that first
successful run, it works offline. None of the prebuilt downloads from
Releases have this requirement at all — ffmpeg is already inside them.

## Releasing a new version

Tag a commit `vX.Y.Z` and push the tag — GitHub Actions builds all three
artifacts (CLI exe, Windows GUI exe, Mac GUI app) and attaches them to a new
Release automatically:

```bash
git tag v1.1.0
git push origin v1.1.0
```

## Development / tests

```bash
pip install -e ".[dev]"
pytest
```
