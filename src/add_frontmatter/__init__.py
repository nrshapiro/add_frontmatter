"""add_frontmatter: prepend a title/frontmatter MP4 onto a folder of MP4s using ffmpeg."""

# Bump this on every release (and pyproject.toml's [project] version to
# match) -- it's what the GUI's title bar and About dialog, and `--version`
# on the CLI, actually display. Habit to keep alongside writing release
# notes: nothing else updates this automatically. The build workflow's
# check-version job fails the build if a pushed version tag doesn't match
# this value and pyproject.toml's (forgotten twice already -- v2.2.2 and
# v2.2.3 both shipped with the GUI showing the previous version).
__version__ = "2.2.5"
