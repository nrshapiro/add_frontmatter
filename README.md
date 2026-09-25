# add-frontmatter

Prepends a "frontmatter" MP4 (e.g. a club opening title) onto every MP4 in a
target folder. Powered by [ffmpeg](https://ffmpeg.org/) under the hood — no
separate install needed, it's bundled into the download below.

Each output file is saved as:

```
<original_stem>_with_frontmatter.mp4
```

---

## For anyone just running this tool

**No Python install needed.** Grab the latest `add-frontmatter.exe` from this
repo's [Releases page](../../releases/latest) — it's a single self-contained
Windows file with everything (including ffmpeg) built in. Just download it
and double-click, or run it from a terminal.

### One-time setup

Open a terminal (PowerShell or Command Prompt) in the folder where you saved
the exe, and run:

```
add-frontmatter --configure
```

It'll ask for your video folder and your frontmatter file, then remember
them for every future run. (These are *your own* folders — the tool ships
with no useful defaults for anyone but Neil, so this step matters.)

### Everyday use

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
- An internet connection the *first* time you run from source — see below.

This project uses the [`imageio-ffmpeg`](https://github.com/imageio/imageio-ffmpeg)
package, which downloads and caches a portable ffmpeg binary automatically
the first time the tool runs from source (a one-time download of a few dozen
MB). After that first run it works fully offline. (The prebuilt `.exe` above
has ffmpeg baked in already, so this doesn't apply to it.)

### Install from source

```bash
pip install -e ".[dev]"
```

This installs `add-frontmatter` as a command, plus `pytest` and
`pyinstaller` for development/building. On Windows this may print a warning
that the installed `.exe` isn't on PATH — see Troubleshooting.

### Building the standalone exe yourself

The GitHub Actions workflow (`.github/workflows/build.yml`) does this
automatically on every push to `main` and on every version tag (`vX.Y.Z`),
publishing the result to Releases. To build one locally instead:

```powershell
pip install -e ".[dev]"
python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
# copy the printed path, then:
pyinstaller --onefile --name add-frontmatter --add-binary "<that path>;." src/add_frontmatter/cli.py
```

The result is `dist/add-frontmatter.exe` — fully self-contained, ffmpeg and
all.

## Usage (all flags)

```bash
add-frontmatter
```

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
```

`--dry-run` processes only the first file found — a real ffmpeg run, not a
simulation — so you can check the result before committing to the whole
folder.

### How it works

1. Scans the target folder for `*.mp4` files (skips the frontmatter file
   itself and anything already ending in `_with_frontmatter`, so reruns are
   safe).
2. **The main video's picture is never re-encoded** — it's byte-copied,
   unchanged, throughout. The tool probes the main video's exact resolution,
   frame rate, and pixel format, then re-encodes a temporary copy of the
   frontmatter's video to match precisely. The two video tracks are then
   joined with a plain stream copy.
3. Audio is built separately from video on purpose. Feeding a freshly
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
4. If the main video has no audio track at all, the output has none either.
   If the main video has audio but the frontmatter doesn't, silence matching
   the main video's audio format fills the frontmatter's portion.
5. Saves each result with the `_with_frontmatter` suffix.

## Troubleshooting

**Windows: "The script add-frontmatter.exe is installed in ... which is not
on PATH"** (only applies when installing from source with `pip`)
The command was installed correctly, but your terminal doesn't know where to
find it yet. Add the folder named in the warning to your PATH via "Edit
environment variables for your account" in Windows search, then reopen your
terminal. Or, simpler: just use the prebuilt exe from Releases instead of
installing from source.

**"No MP4 files to process"**
Either the target folder is genuinely empty of MP4s, or everything in it
already has the `_with_frontmatter` suffix (the tool skips those on purpose,
so reruns don't double-process files).

**ffmpeg-related errors on first run (source installs only)**
The very first run from source needs an internet connection to download and
cache a portable ffmpeg binary (via `imageio-ffmpeg`). After that first
successful run, it works offline. The prebuilt exe from Releases doesn't
have this requirement at all — ffmpeg is already inside it.

## Releasing a new version

Tag a commit `vX.Y.Z` and push the tag — GitHub Actions builds the exe and
attaches it to a new Release automatically:

```bash
git tag v1.1.0
git push origin v1.1.0
```

## Development / tests

```bash
pip install -e ".[dev]"
pytest
```
