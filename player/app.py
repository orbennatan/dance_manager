"""
Main GUI application for the Dance Manager.

Layout
------
┌──────────────────────────────────────────────┐
│  Dance Manager                               │
│                                              │
│  Library folder: [_________________] [Open]  │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │ video1.mp4   sessions: 2  score: 50% │    │
│  │ video2.mp4   sessions: 0  score:  0% │    │
│  │ …                                    │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  [▶ Play Suggested]  [▶ Play Selected]       │
│  Status: …                                   │
└──────────────────────────────────────────────┘

The "Play Suggested" button chooses the most overdue video automatically
while "Play Selected" plays whichever row the user has highlighted.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from .scheduler import next_video, prioritize
from .tracker import SessionTracker
from .video_player import play

# Video file extensions recognised by the application
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"}

# Path to persist session data, stored alongside the application
_DEFAULT_DATA_FILE = os.path.join(os.path.expanduser("~"), ".dance_manager_data.json")


class DanceManagerApp(tk.Tk):
    """Root window of the Dance Manager application."""

    def __init__(self, data_file: str = _DEFAULT_DATA_FILE) -> None:
        super().__init__()
        self.title("Dance Manager")
        self.resizable(True, True)
        self.minsize(600, 420)

        self._tracker = SessionTracker(data_file)
        self._folder: Optional[str] = None
        self._playing = False  # guard against concurrent playback

        self._build_ui()
        self._refresh_table()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        padding = {"padx": 10, "pady": 6}

        # ── Folder row ────────────────────────────────────────────────
        folder_frame = tk.Frame(self)
        folder_frame.pack(fill="x", **padding)

        tk.Label(folder_frame, text="Library folder:").pack(side="left")
        self._folder_var = tk.StringVar(value="(none)")
        tk.Label(
            folder_frame,
            textvariable=self._folder_var,
            anchor="w",
            relief="sunken",
            width=50,
        ).pack(side="left", padx=6)
        tk.Button(folder_frame, text="Open…", command=self._choose_folder).pack(side="left")

        # ── Video table ───────────────────────────────────────────────
        table_frame = tk.Frame(self)
        table_frame.pack(fill="both", expand=True, **padding)

        columns = ("filename", "sessions", "score", "last_viewed")
        self._tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self._tree.heading("filename", text="Video")
        self._tree.heading("sessions", text="Sessions")
        self._tree.heading("score", text="Mastery")
        self._tree.heading("last_viewed", text="Last Viewed")
        self._tree.column("filename", width=280, anchor="w")
        self._tree.column("sessions", width=80, anchor="center")
        self._tree.column("score", width=100, anchor="center")
        self._tree.column("last_viewed", width=180, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # ── Button row ────────────────────────────────────────────────
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", **padding)

        self._btn_suggest = tk.Button(
            btn_frame,
            text="▶  Play Suggested",
            command=self._play_suggested,
            width=20,
        )
        self._btn_suggest.pack(side="left", padx=(0, 8))

        self._btn_selected = tk.Button(
            btn_frame,
            text="▶  Play Selected",
            command=self._play_selected,
            width=20,
        )
        self._btn_selected.pack(side="left")

        # ── Status bar ────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Choose a folder to begin.")
        status_bar = tk.Label(
            self,
            textvariable=self._status_var,
            anchor="w",
            relief="sunken",
        )
        status_bar.pack(fill="x", side="bottom", ipady=2, padx=10, pady=(0, 6))

    # ------------------------------------------------------------------
    # Folder management
    # ------------------------------------------------------------------

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select video library folder")
        if folder:
            self._folder = folder
            self._folder_var.set(folder)
            self._scan_folder()

    def _scan_folder(self) -> None:
        if not self._folder:
            return
        videos = sorted(
            f
            for f in os.listdir(self._folder)
            if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS
        )
        if not videos:
            self._status_var.set("No video files found in the selected folder.")
            return
        self._tracker.register_videos(videos)
        self._refresh_table()
        self._status_var.set(f"Loaded {len(videos)} video(s) from {self._folder}")

    # ------------------------------------------------------------------
    # Table management
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        """Repopulate the treeview from tracker records, sorted by priority."""
        for row in self._tree.get_children():
            self._tree.delete(row)

        records = prioritize(self._tracker.all_records())
        for rec in records:
            last = rec.last_viewed[:19].replace("T", " ") if rec.last_viewed else "—"
            self._tree.insert(
                "",
                "end",
                iid=rec.filename,
                values=(
                    rec.filename,
                    rec.sessions,
                    f"{rec.mastery_score * 100:.0f}%",
                    last,
                ),
            )

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def _play_suggested(self) -> None:
        records = self._tracker.all_records()
        if not records:
            messagebox.showinfo("No videos", "Open a folder with video files first.")
            return
        record = next_video(records)
        if record is None:
            return
        self._start_playback(record.filename)

    def _play_selected(self) -> None:
        selection = self._tree.selection()
        if not selection:
            messagebox.showinfo("No selection", "Please select a video from the list.")
            return
        filename = selection[0]  # iid == filename
        self._start_playback(filename)

    def _start_playback(self, filename: str) -> None:
        if self._playing:
            messagebox.showwarning("Already playing", "A video is already playing.")
            return
        if not self._folder:
            messagebox.showerror("No folder", "Please open a video library folder first.")
            return
        filepath = os.path.join(self._folder, filename)
        if not os.path.isfile(filepath):
            messagebox.showerror("File not found", f"Could not find:\n{filepath}")
            return

        self._playing = True
        self._status_var.set(f"Playing: {filename}  …  close the player to record the session.")
        self._btn_suggest.configure(state="disabled")
        self._btn_selected.configure(state="disabled")

        # Run playback in a background thread so the GUI stays responsive
        thread = threading.Thread(target=self._playback_thread, args=(filename, filepath), daemon=True)
        thread.start()

    def _playback_thread(self, filename: str, filepath: str) -> None:
        """Background thread: play the video, then update state on the main thread."""
        try:
            play(filepath)
        except (FileNotFoundError, RuntimeError) as exc:
            self.after(0, lambda: self._on_playback_error(str(exc)))
            return
        # Schedule the session recording on the main thread
        self.after(0, lambda: self._on_playback_finished(filename))

    def _on_playback_finished(self, filename: str) -> None:
        self._playing = False
        self._tracker.record_session(filename)
        self._refresh_table()
        record = self._tracker.get_record(filename)
        self._status_var.set(
            f'Session recorded for "{filename}" '
            f"(sessions: {record.sessions}, mastery: {record.mastery_score * 100:.0f}%)"
        )
        self._btn_suggest.configure(state="normal")
        self._btn_selected.configure(state="normal")

    def _on_playback_error(self, message: str) -> None:
        self._playing = False
        messagebox.showerror("Playback error", message)
        self._status_var.set("Playback error — see dialog.")
        self._btn_suggest.configure(state="normal")
        self._btn_selected.configure(state="normal")


def run(data_file: str = _DEFAULT_DATA_FILE) -> None:
    """Create and run the Dance Manager application."""
    app = DanceManagerApp(data_file=data_file)
    app.mainloop()
