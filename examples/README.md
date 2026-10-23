# Sample files

Tiny synthetic files for trying the app out before using it on a real
recording — see the "Try it out first" section in the main
[README](../README.md) for the actual steps.

- **`sample_frontmatter.mp4`** — a 2-second color-bars title card
  reading "SPS OPENING", standing in for a real opening/logo video.
- **`sample_meeting/`** — a 6-second fake "meeting recording"
  (`GMT20261023-150000_Recording.mp4`, orange screen with a running
  "MEETING T+HH:MM:SS" counter burned into the picture) plus its
  companion Zoom chat log (`GMT20261023-150000_RecordingnewChat.txt`),
  with an `iStart` marker 2 seconds in. Keep the video and chat log
  together in this folder — the app finds the chat log by looking for a
  same-named `.txt` file next to the video, same as it would for a real
  download from Zoom.

**What to look for:** play the file the app produces. It should open
with the "SPS OPENING" color-bars card, then cut straight to the orange
screen already reading **T+00:00:02** (not T+00:00:00) — proof the app
found the `iStart` marker in the chat log and cut the first 2 seconds
of lead-in, exactly as it would with a real meeting recording and a
real `!START`/`iStart` typed in the chat.

Everything here is generated, not an actual meeting — there's nothing
sensitive in it, and it's safe to download, share, or re-run as many
times as you like.

If you're curious about the other chat-log format this tool also handles
(the older, plain `"..._Recording.txt"` naming, which uses wall-clock
timestamps instead of elapsed time — see `trim.py`'s module docstring for
why that distinction matters), there's a second example of that under
[`../tests/fixtures/wallclock_chat/`](../tests/fixtures/wallclock_chat/).
