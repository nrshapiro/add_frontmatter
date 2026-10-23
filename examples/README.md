# Sample files

Tiny synthetic files for trying the app out before using it on a real
recording — see the "Try it out first" section in the main
[README](../README.md) for the actual steps.

- **`sample_frontmatter.mp4`** — a 2-second navy clip standing in for a
  real opening/logo video.
- **`sample_meeting/`** — a 6-second fake "meeting recording"
  (`GMT20261023-150000_Recording_160x120.mp4`) plus its companion Zoom
  chat log (`GMT20261023-150000_RecordingnewChat.txt`), with an `iStart`
  marker 2 seconds in. Keep the video and chat log together in this
  folder — the app finds the chat log by looking for a same-named `.txt`
  file next to the video, same as it would for a real download from Zoom.

Everything here is generated, not an actual meeting — there's nothing
sensitive in it, and it's safe to download, share, or re-run as many
times as you like.

If you're curious about the other chat-log format this tool also handles
(the older, plain `"..._Recording.txt"` naming, which uses wall-clock
timestamps instead of elapsed time — see `trim.py`'s module docstring for
why that distinction matters), there's a second example of that under
[`../tests/fixtures/wallclock_chat/`](../tests/fixtures/wallclock_chat/).
