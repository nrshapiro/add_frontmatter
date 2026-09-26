"""GUI for add_frontmatter.

Wraps the existing core.process_video() / config.py logic in a window so
non-Python users can just pick MP4 files via a normal file-open dialog and
click Process — no terminal required. All the actual video work is
unchanged from the CLI; this file only adds the window.

Uses a plain file dialog (tkinter.filedialog) rather than drag-and-drop —
that needs no extra third-party package (Tkinter itself has no native
drag-and-drop), which keeps this dependency-free and simpler to package
reliably across Windows and Mac.
"""

from __future__ import annotations

import queue
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .config import load_config, save_config
from .core import FfmpegNotFoundError, already_processed, get_ffmpeg_path, process_video
from .trim import DEFAULT_TRIGGER, maybe_trim, strip_offset_token

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

APP_DESCRIPTION = (
    "Automates adding a lead-in “frontmatter” video (e.g. a logo) to the front "
    "of a Zoom-recorded meeting video (both MP4). If a Zoom chat log with the same "
    f"base name is found next to a video, it looks for a chat line “{DEFAULT_TRIGGER}” "
    "(case-insensitive) and trims the start of the video to that point before prepending the "
    "frontmatter. Processes as many files as you add, in one batch."
)


def _resource_path(name: str) -> Path:
    """Find a bundled asset whether running from source, from a normal pip
    install, or from a PyInstaller-frozen executable (which unpacks data
    files to sys._MEIPASS). The PyInstaller spec places assets at the same
    'add_frontmatter/assets/' relative path used here, so one lookup covers
    all three cases."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "add_frontmatter" / "assets" / name
    return ASSETS_DIR / name


class FrontmatterGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"Add Frontmatter — v{__version__}")
        self.root.geometry("640x580")
        self.root.minsize(520, 460)

        self.cfg = load_config()
        self.frontmatter_path = tk.StringVar(value=self.cfg.get("frontmatter", ""))
        self.output_dir_path = tk.StringVar(value=self.cfg.get("output_dir", "") or "")
        self.auto_trim = tk.BooleanVar(value=self.cfg.get("auto_trim", True))
        self.queued_files: list[Path] = []
        self.result_queue: "queue.Queue[tuple[str, str, bool]]" = queue.Queue()
        self.worker_running = False

        self._build_widgets()
        self._poll_result_queue()

        if not self.frontmatter_path.get():
            self.root.after(300, self._prompt_first_run_setup)

    # ---------------------------------------------------------- layout ----

    def _build_widgets(self) -> None:
        header = ttk.Frame(self.root, padding=(12, 12, 12, 6))
        header.pack(fill="x")

        logo_path = _resource_path("sps_logo_96.png")
        if logo_path.is_file():
            self._logo_img = tk.PhotoImage(file=str(logo_path))
            ttk.Label(header, image=self._logo_img).pack(side="left", padx=(0, 10))

        title_frame = ttk.Frame(header)
        title_frame.pack(side="left", fill="x", expand=True)
        title_row = ttk.Frame(title_frame)
        title_row.pack(anchor="w", fill="x")
        ttk.Label(title_row, text="Add Frontmatter", font=("Segoe UI", 16, "bold")).pack(side="left")
        version_label = ttk.Label(
            title_row, text=f"v{__version__}", foreground="#0645AD", cursor="hand2",
        )
        version_label.pack(side="left", padx=(8, 0), pady=(4, 0))
        version_label.bind("<Button-1>", lambda _e: self._show_about())
        ttk.Label(
            title_frame,
            text="Click “Add Files…” to choose MP4s, then click Process.",
        ).pack(anchor="w")
        ttk.Label(
            title_frame,
            text=APP_DESCRIPTION,
            wraplength=560,
            justify="left",
            foreground="#444444",
        ).pack(anchor="w", pady=(6, 0))

        settings_frame = ttk.LabelFrame(self.root, text="Settings", padding=8)
        settings_frame.pack(fill="x", padx=12, pady=(0, 6))

        ttk.Label(settings_frame, text="Frontmatter video:").grid(row=0, column=0, sticky="w")
        ttk.Entry(settings_frame, textvariable=self.frontmatter_path, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Button(settings_frame, text="Choose…", command=self._choose_frontmatter).grid(row=0, column=2)

        ttk.Label(settings_frame, text="Output folder:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(settings_frame, textvariable=self.output_dir_path, state="readonly").grid(
            row=1, column=1, sticky="ew", padx=6, pady=(4, 0)
        )
        ttk.Button(settings_frame, text="Choose…", command=self._choose_output_dir).grid(
            row=1, column=2, pady=(4, 0)
        )

        ttk.Checkbutton(
            settings_frame,
            text=f'Auto-trim lead-in when a chat log with "{DEFAULT_TRIGGER}" is found next to a video',
            variable=self.auto_trim,
            command=self._save_settings,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        settings_frame.columnconfigure(1, weight=1)

        list_frame = ttk.LabelFrame(self.root, text="Files to process", padding=8)
        list_frame.pack(fill="both", expand=True, padx=12, pady=6)

        self.file_list = tk.Listbox(list_frame, selectmode="extended")
        self.file_list.pack(fill="both", expand=True, side="left")
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.file_list.yview)
        list_scroll.pack(side="right", fill="y")
        self.file_list.configure(yscrollcommand=list_scroll.set)

        btn_row = ttk.Frame(self.root, padding=(12, 0))
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Add Files…", command=self._add_files_dialog).pack(side="left")
        ttk.Button(btn_row, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Clear", command=self._clear_files).pack(side="left")
        self.process_btn = ttk.Button(btn_row, text="Process", command=self._start_processing)
        self.process_btn.pack(side="right")

        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill="x", padx=12, pady=(6, 0))

        log_frame = ttk.LabelFrame(self.root, text="Log", padding=4)
        log_frame.pack(fill="both", expand=False, padx=12, pady=(6, 12))
        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True)

    # ------------------------------------------------------- file mgmt ----

    def _add_files_dialog(self) -> None:
        paths = filedialog.askopenfilenames(title="Choose MP4 files", filetypes=[("MP4 video", "*.mp4")])
        self._add_paths(Path(p) for p in paths)

    def _add_paths(self, paths) -> None:
        added = 0
        for p in paths:
            if p.suffix.lower() != ".mp4":
                continue
            if p in self.queued_files:
                continue
            self.queued_files.append(p)
            self.file_list.insert("end", p.name)
            added += 1
        if added:
            self._log(f"Added {added} file(s).")

    def _remove_selected(self) -> None:
        for idx in reversed(self.file_list.curselection()):
            del self.queued_files[idx]
            self.file_list.delete(idx)

    def _clear_files(self) -> None:
        self.queued_files.clear()
        self.file_list.delete(0, "end")

    # --------------------------------------------------------- settings ----

    def _choose_frontmatter(self) -> None:
        path = filedialog.askopenfilename(title="Choose the frontmatter MP4", filetypes=[("MP4 video", "*.mp4")])
        if path:
            self.frontmatter_path.set(path)
            self._save_settings()

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.output_dir_path.set(path)
            self._save_settings()

    def _save_settings(self) -> None:
        # target isn't used by the GUI (files are queued individually), but
        # config.py's schema expects it — reuse the frontmatter's own folder
        # as a harmless placeholder so the CLI's --configure output stays
        # compatible if someone also uses the command line.
        fm = self.frontmatter_path.get()
        target = str(Path(fm).parent) if fm else self.cfg.get("target", "")
        save_config(target, fm, self.output_dir_path.get() or None, self.auto_trim.get())
        self.cfg = load_config()

    def _prompt_first_run_setup(self) -> None:
        messagebox.showinfo(
            "First-time setup",
            "Before processing, choose your frontmatter MP4 (and optionally an "
            "output folder) using the Settings panel above.",
        )

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About Add Frontmatter",
            f"Add Frontmatter — v{__version__}\n\n{APP_DESCRIPTION}\n\n"
            "github.com/nrshapiro/add_frontmatter",
        )

    # --------------------------------------------------------- logging ----

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # -------------------------------------------------------- processing ----

    def _start_processing(self) -> None:
        if self.worker_running:
            return
        if not self.queued_files:
            messagebox.showwarning("Nothing to do", "Add some MP4 files first.")
            return
        frontmatter = self.frontmatter_path.get()
        if not frontmatter or not Path(frontmatter).is_file():
            messagebox.showerror("Missing frontmatter", "Choose a frontmatter MP4 in Settings first.")
            return

        output_dir = Path(self.output_dir_path.get()) if self.output_dir_path.get() else self.queued_files[0].parent / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            ffmpeg_path = get_ffmpeg_path()
        except FfmpegNotFoundError as exc:
            messagebox.showerror("ffmpeg not available", str(exc))
            return

        files = list(self.queued_files)
        self.worker_running = True
        self.process_btn.configure(state="disabled")
        self.progress.configure(maximum=len(files), value=0)
        self._log(f"\nStarting: {len(files)} file(s) → {output_dir}")

        thread = threading.Thread(
            target=self._worker,
            args=(ffmpeg_path, Path(frontmatter), files, output_dir, self.auto_trim.get()),
            daemon=True,
        )
        thread.start()

    def _worker(
        self, ffmpeg_path: str, frontmatter: Path, files: list[Path], output_dir: Path, auto_trim: bool,
    ) -> None:
        for video in files:
            existing = already_processed(video, output_dir)
            if existing is not None:
                self.result_queue.put((video.name, f"skipped: already processed -> {existing.name}", True))
                continue

            with tempfile.TemporaryDirectory() as tmp:
                if auto_trim:
                    working_video, trim_msg, offset_seconds = maybe_trim(ffmpeg_path, video, Path(tmp), DEFAULT_TRIGGER)
                else:
                    working_video, trim_msg, offset_seconds = video, "trimming disabled", None
                self.result_queue.put((video.name, f"trim: {trim_msg}", False))

                success, message = process_video(
                    ffmpeg_path, frontmatter, working_video, output_dir,
                    output_name_stem=strip_offset_token(video.stem), offset_seconds=offset_seconds,
                )
            self.result_queue.put((video.name, f"{'done' if success else 'FAILED'}: {message}", True))
        self.result_queue.put(("__DONE__", "", True))

    def _poll_result_queue(self) -> None:
        try:
            while True:
                name, message, is_terminal = self.result_queue.get_nowait()
                if name == "__DONE__":
                    self.worker_running = False
                    self.process_btn.configure(state="normal")
                    self._log("All done.")
                else:
                    self._log(f"{name}: {message}")
                    if is_terminal:
                        self.progress.configure(value=self.progress["value"] + 1)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_result_queue)


def main() -> int:
    root = tk.Tk()
    icon_path = _resource_path("sps_logo.ico" if sys.platform == "win32" else "sps_logo.icns")
    try:
        if sys.platform == "win32" and icon_path.is_file():
            root.iconbitmap(str(icon_path))
    except tk.TclError:
        pass  # icon is cosmetic only; never block startup over it
    FrontmatterGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
