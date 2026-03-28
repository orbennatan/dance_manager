"""
Dance Manager – Video Player
==============================
Tkinter + python-vlc video player with integrated spaced-repetition scoring.

Spaced-repetition model
-----------------------
* Every video starts with historical_score = 0.0  (Zero-Trust Initialization).
* Pool A (0–59)   → Learning  → 60 % of session time
* Pool B (60–84)  → Familiar  → 25 % of session time
* Pool C (85–100) → Mastered  → 15 % of session time
* Session score is reduced by backward-seek (rewind) penalties.
* EMA formula:  new = 0.30 * session_score + 0.70 * old_historical
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

try:
	import vlc
except ImportError:
	print(
		"Missing dependency: python-vlc.\n"
		"Install it with: pip install python-vlc"
	)
	raise

import db
import recommender
from scorer import SessionScorer


VIDEO_FOLDER = Path(r"C:\Users\orben\OneDrive\DanceManager\Dances\9")
VIDEO_EXTENSIONS = {
	".mp4",
	".mkv",
	".avi",
	".mov",
	".wmv",
	".flv",
	".webm",
	".m4v",
}
SEEK_STEP_MS = 10_000

# Score display: minimum play_count before the badge shows a number
# (below this threshold the badge reads "New").
SCORE_MIN_PLAYS_TO_SHOW = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_time(ms: int) -> str:
	if ms < 0:
		return "0:00"
	s = ms // 1000
	return f"{s // 60}:{s % 60:02d}"


def _score_badge(stat: db.DanceStat) -> str:
	"""Short badge shown next to each filename in the sidebar listbox."""
	if stat.play_count < SCORE_MIN_PLAYS_TO_SHOW:
		return "[ A   New]"
	score = stat.historical_score
	pool = recommender.pool_label(score).split("–")[0].strip()  # "A", "B", or "C"
	return f"[{pool} {score:5.1f}]"


class VideoPlayerApp:
	def __init__(self, root: tk.Tk, folder: Path) -> None:
		self.root = root
		self.folder = folder
		self.root.title("Dance Manager")
		self.root.geometry("1200x700")

		# VLC
		self.instance = vlc.Instance("--reset-plugins-cache", "--quiet")
		self.player = self.instance.media_player_new()

		# Database: initialise and scan folder
		db.init_db()
		self.files = self._load_files()
		self.current_index = 0
		self._sync_db_with_folder()

		# Session scorer for the currently-playing video
		self._scorer: SessionScorer | None = None
		self._last_seek_pos_ms: int = 0
		self._end_handled_for_current_media = False

		# Seeking flag (suppresses progress-bar polling during drag)
		self._seeking = False

		# Session playlist (ordered by recommender)
		self._session_minutes: float = 30.0
		self._session_queue: list[str] = []   # filenames in recommended order
		self._session_pos: int = 0            # index into _session_queue

		# Ask the user how long they want to practise
		self._session_minutes = _ask_session_length(self.root)
		self._rebuild_session_queue()

		self._build_ui()
		self._bind_player_to_canvas()
		self._configure_vlc_input()
		self._bind_keyboard_shortcuts()
		self._poll_progress()

		if self.files:
			# Start with the first video in the session queue if available
			start_index = self._session_start_index()
			self.listbox.selection_set(start_index)
			self.listbox.activate(start_index)
			self._play_index(start_index)
		else:
			messagebox.showwarning(
				"No videos found",
				f"No supported video files found in:\n{self.folder}",
			)

		self.root.protocol("WM_DELETE_WINDOW", self._on_close)

	def _load_files(self) -> list[Path]:
		if not self.folder.exists():
			self.folder.mkdir(parents=True, exist_ok=True)
		return [
			f
			for f in sorted(self.folder.iterdir())
			if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
		]

	def _sync_db_with_folder(self) -> None:
		"""Ensure every video file on disk has a DB row (zero-trust init)."""
		for f in self.files:
			db.get_or_create(f.name)

	def _build_ui(self) -> None:
		container = tk.Frame(self.root)
		container.pack(fill=tk.BOTH, expand=True)

		# ── Left sidebar ─────────────────────────────────────────────
		left = tk.Frame(container, width=340)
		left.pack(side=tk.LEFT, fill=tk.Y)
		left.pack_propagate(False)

		self.folder_label = tk.Label(
			left,
			text=f"Folder:\n{self.folder}",
			justify=tk.LEFT,
			anchor="w",
			wraplength=320,
		)
		self.folder_label.pack(fill=tk.X, padx=10, pady=(10, 2))

		# Pool legend
		legend_frame = tk.Frame(left)
		legend_frame.pack(fill=tk.X, padx=10, pady=(0, 4))
		for text, colour in [
			("A: Learning  (score 0–59)", "#d9534f"),
			("B: Familiar  (score 60–84)", "#f0ad4e"),
			("C: Mastered  (score 85+)",   "#5cb85c"),
		]:
			tk.Label(legend_frame, text=text, fg=colour, anchor="w",
					 font=("TkDefaultFont", 8)).pack(anchor="w")

		# Listbox with scrollbars
		list_frame = tk.Frame(left)
		list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

		scrollbar_y = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
		scrollbar_x = tk.Scrollbar(list_frame, orient=tk.HORIZONTAL)

		self.listbox = tk.Listbox(
			list_frame,
			exportselection=False,
			yscrollcommand=scrollbar_y.set,
			xscrollcommand=scrollbar_x.set,
			font=("Courier", 9),
		)
		scrollbar_y.config(command=self.listbox.yview)
		scrollbar_x.config(command=self.listbox.xview)

		scrollbar_y.pack(side=tk.RIGHT,  fill=tk.Y)
		scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
		self.listbox.pack(fill=tk.BOTH, expand=True)

		self._populate_listbox()
		self.listbox.bind("<<ListboxSelect>>", self._on_select)

		# Controls
		controls = tk.Frame(left)
		controls.pack(fill=tk.X, padx=10, pady=10)
		tk.Button(controls, text="⏮ Prev", command=self.play_previous).pack(side=tk.LEFT, padx=3)
		self.play_pause_button = tk.Button(
			controls, text="⏸ Pause", command=self.toggle_play_pause
		)
		self.play_pause_button.pack(side=tk.LEFT, padx=3)
		tk.Button(controls, text="⏹ Stop", command=self.stop).pack(side=tk.LEFT, padx=3)
		tk.Button(controls, text="⏭ Next", command=self.play_next).pack(side=tk.LEFT, padx=3)

		# Session info
		session_info_frame = tk.Frame(left)
		session_info_frame.pack(fill=tk.X, padx=10, pady=(0, 4))
		self.session_info_var = tk.StringVar(value="")
		tk.Label(
			session_info_frame,
			textvariable=self.session_info_var,
			anchor="w",
			font=("TkDefaultFont", 8),
			fg="#555555",
		).pack(side=tk.LEFT, fill=tk.X, expand=True)
		tk.Button(
			session_info_frame,
			text="New session",
			command=self._new_session,
			font=("TkDefaultFont", 8),
		).pack(side=tk.RIGHT)
		right = tk.Frame(container, bg="black")
		right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

		self.video_canvas = tk.Canvas(
			right,
			bg="black",
			highlightthickness=0,
			cursor="arrow",
			takefocus=1,
		)
		self.video_canvas.pack(fill=tk.BOTH, expand=True)

		# Score / pool indicator panel
		score_frame = tk.Frame(right, bg="#111111")
		score_frame.pack(fill=tk.X, padx=0, pady=0)

		# Coloured pool badge (background colour changes per pool)
		self.pool_badge = tk.Label(
			score_frame,
			text="",
			bg="#555555", fg="white",
			anchor="center",
			font=("TkDefaultFont", 10, "bold"),
			padx=10, pady=4,
		)
		self.pool_badge.pack(side=tk.LEFT, padx=(6, 0), pady=4)

		# Historical score text next to the badge
		self.score_info_var = tk.StringVar(value="")
		tk.Label(
			score_frame,
			textvariable=self.score_info_var,
			bg="#111111", fg="#dddddd",
			anchor="w", font=("TkDefaultFont", 10),
		).pack(side=tk.LEFT, padx=8)

		# Rewind counter (right-aligned)
		self.rewind_var = tk.StringVar(value="")
		tk.Label(
			score_frame,
			textvariable=self.rewind_var,
			bg="#111111", fg="#e8a838",
			anchor="e", font=("TkDefaultFont", 10),
		).pack(side=tk.RIGHT, padx=10)

		# Progress bar row
		progress_frame = tk.Frame(right, bg="black")
		progress_frame.pack(fill=tk.X, padx=6, pady=(2, 4))

		self.time_current_var = tk.StringVar(value="0:00")
		tk.Label(
			progress_frame,
			textvariable=self.time_current_var,
			bg="black", fg="white", width=6, anchor="w",
		).pack(side=tk.LEFT)

		self.progress_var = tk.DoubleVar(value=0.0)
		self.progress_bar = ttk.Scale(
			progress_frame,
			variable=self.progress_var,
			from_=0.0,
			to=1000.0,
			orient=tk.HORIZONTAL,
		)
		self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
		self.progress_bar.bind("<ButtonPress-1>",   self._on_progress_press)
		self.progress_bar.bind("<ButtonRelease-1>", self._on_progress_release)

		self.time_total_var = tk.StringVar(value="0:00")
		tk.Label(
			progress_frame,
			textvariable=self.time_total_var,
			bg="black", fg="white", width=6, anchor="e",
		).pack(side=tk.RIGHT)

		self.status_var = tk.StringVar(value="Ready")
		status = tk.Label(self.root, textvariable=self.status_var, anchor="w")
		status.pack(fill=tk.X)

	# ── Sidebar helpers ──────────────────────────────────────────────────

	def _populate_listbox(self) -> None:
		"""Rebuild all listbox entries with current DB scores."""
		self.listbox.delete(0, tk.END)
		for f in self.files:
			stat = db.get_stat(f.name)
			badge = _score_badge(stat) if stat else "[ ?   ???]"
			self.listbox.insert(tk.END, f"{badge} {f.name}")
		self._colour_listbox()

	def _colour_listbox(self) -> None:
		"""Colour each row according to its pool."""
		for i, f in enumerate(self.files):
			stat = db.get_stat(f.name)
			if stat is None:
				continue
			score = stat.historical_score
			if score <= recommender.POOL_A_MAX:
				colour = "#d9534f"
			elif score <= recommender.POOL_B_MAX:
				colour = "#f0ad4e"
			else:
				colour = "#5cb85c"
			self.listbox.itemconfig(i, foreground=colour)

	def _bind_keyboard_shortcuts(self) -> None:
		self.root.bind_all("<Left>", self._on_seek_left)
		self.root.bind_all("<Right>", self._on_seek_right)
		self.root.bind_all("<space>", self._on_space)
		self.video_canvas.bind("<Button-1>", self._on_video_click)

	def _on_space(self, _event: tk.Event) -> str:
		self.toggle_play_pause()
		return "break"

	def _on_video_click(self, _event: tk.Event) -> str:
		self.video_canvas.focus_set()
		self.toggle_play_pause()
		return "break"

	def _on_seek_left(self, _event: tk.Event) -> str:
		self.seek_relative(-SEEK_STEP_MS)
		return "break"

	def _on_seek_right(self, _event: tk.Event) -> str:
		self.seek_relative(SEEK_STEP_MS)
		return "break"

	@staticmethod
	def _fmt_time(ms: int) -> str:
		if ms < 0:
			return "0:00"
		s = ms // 1000
		return f"{s // 60}:{s % 60:02d}"

	def _poll_progress(self) -> None:
		if not self._seeking:
			length_ms = self.player.get_length()
			current_ms = self.player.get_time()
			state = self.player.get_state()
			if length_ms > 0:
				self.progress_var.set(current_ms / length_ms * 1000)
				self.time_total_var.set(_fmt_time(length_ms))
				# Scorer may not have the length yet if media just started
				if self._scorer and self._scorer._video_length_ms == 0:
					stat = db.get_stat(self.files[self.current_index].name)
					old_score = stat.historical_score if stat else 0.0
					self._scorer.start(length_ms, old_score)
			else:
				self.progress_var.set(0.0)
			self.time_current_var.set(_fmt_time(current_ms))

			# Auto-advance when a video ends
			if state == vlc.State.Ended and not self._end_handled_for_current_media:
				self._end_handled_for_current_media = True
				self.status_var.set("Video ended. Loading next...")
				self.root.after(100, self.play_next)
		self.root.after(500, self._poll_progress)

	def _on_progress_press(self, _event: tk.Event) -> None:
		self._last_seek_pos_ms = self.player.get_time()
		self._seeking = True

	def _on_progress_release(self, _event: tk.Event) -> None:
		length_ms = self.player.get_length()
		if length_ms > 0:
			target_ms = int(self.progress_var.get() / 1000 * length_ms)
			if self._scorer and target_ms < self._last_seek_pos_ms:
				self._scorer.register_rewind(self._last_seek_pos_ms, target_ms)
				self._update_rewind_display()
			self.player.set_time(target_ms)
		self._seeking = False

	# ── VLC plumbing ─────────────────────────────────────────────────────

	def _bind_player_to_canvas(self) -> None:
		self.root.update_idletasks()
		hwnd = self.video_canvas.winfo_id()
		if sys.platform.startswith("win"):
			self.player.set_hwnd(hwnd)
		elif sys.platform.startswith("linux"):
			self.player.set_xwindow(hwnd)
		elif sys.platform == "darwin":
			self.player.set_nsobject(hwnd)

	def _configure_vlc_input(self) -> None:
		if hasattr(self.player, "video_set_mouse_input"):
			self.player.video_set_mouse_input(False)
		if hasattr(self.player, "video_set_key_input"):
			self.player.video_set_key_input(False)

	# ── Scoring helpers ──────────────────────────────────────────────────

	def _start_scorer(self, filename: str) -> None:
		"""Create a fresh scorer for the video that is about to play."""
		stat = db.get_stat(filename)
		old_score = stat.historical_score if stat else 0.0
		length_ms = self.player.get_length()   # may still be 0; polled later
		self._scorer = SessionScorer(filename=filename)
		self._scorer.start(length_ms, old_score)
		self._update_score_display(filename, old_score)
		self.rewind_var.set("")

	def _finalize_scorer(self) -> None:
		"""Save the current session result to DB and refresh the sidebar."""
		if self._scorer is None:
			return
		result = self._scorer.finalize()
		if self._scorer._started:
			db.update_score(result.filename, result.new_historical)
			self._populate_listbox()
			if 0 <= self.current_index < self.listbox.size():
				self.listbox.selection_clear(0, tk.END)
				self.listbox.selection_set(self.current_index)
				self.listbox.activate(self.current_index)
		self._scorer = None

	# Pool badge colours match the sidebar traffic-light scheme
	_POOL_COLOURS = {
		"A": ("#c0392b", "white"),   # red    – Learning
		"B": ("#d68910", "white"),   # amber  – Familiar
		"C": ("#1e8449", "white"),   # green  – Mastered
	}

	def _update_score_display(self, filename: str, score: float) -> None:
		pool_full = recommender.pool_label(score)          # "A – Learning" etc.
		pool_letter = pool_full.split("–")[0].strip()     # "A", "B", or "C"
		pool_name   = pool_full.split("–")[1].strip()     # "Learning" etc.

		bg, fg = self._POOL_COLOURS.get(pool_letter, ("#555555", "white"))
		self.pool_badge.config(
			text=f" Pool {pool_letter} • {pool_name} ",
			bg=bg, fg=fg,
		)

		if score == 0.0 and db.get_stat(filename) and db.get_stat(filename).play_count == 0:
			score_text = "Score: New"
		else:
			score_text = f"Score: {score:.1f} / 100"
		self.score_info_var.set(score_text)

		self.root.title(f"Dance Manager  —  {filename}  [{pool_full}  {score_text}]")

	def _update_rewind_display(self) -> None:
		if self._scorer:
			count = len(self._scorer._rewind_penalties)
			self.rewind_var.set(f"↩ Rewinds this session: {count}")

	# ── Session queue ───────────────────────────────────────────────────

	def _rebuild_session_queue(self) -> None:
		"""Ask the recommender to build a fresh ordered playlist."""
		all_stats = db.get_all()
		avail = {f.name for f in self.files}
		self._session_queue = recommender.build_session(
			all_stats, avail,
			session_minutes=self._session_minutes,
		)
		self._session_pos = 0

	def _session_start_index(self) -> int:
		"""Return the files[] index of the first video in the session queue."""
		if self._session_queue:
			fname = self._session_queue[0]
			for i, f in enumerate(self.files):
				if f.name == fname:
					return i
		return 0

	def _advance_session_pos(self, played_filename: str) -> None:
		"""Move the session pointer forward when a video finishes or is switched."""
		if self._session_pos < len(self._session_queue):
			if self._session_queue[self._session_pos] == played_filename:
				self._session_pos += 1

	def _next_session_index(self) -> int | None:
		"""Return files[] index of the next queued video, or None if session done."""
		if self._session_pos < len(self._session_queue):
			pos = self._session_pos
			current_name = self.files[self.current_index].name if self.files else None

			# Skip the current file so "next" never replays the same video.
			while pos < len(self._session_queue) and self._session_queue[pos] == current_name:
				pos += 1

			if pos < len(self._session_queue):
				fname = self._session_queue[pos]
				for i, f in enumerate(self.files):
					if f.name == fname:
						return i
		return None

	def _new_session(self) -> None:
		"""Ask for a new session length, rebuild queue, and jump to first video."""
		new_minutes = _ask_session_length(self.root)
		if new_minutes is None:
			return
		self._session_minutes = new_minutes
		self._rebuild_session_queue()
		start = self._session_start_index()
		self._play_index(start)
		self._update_session_info()

	def _update_session_info(self) -> None:
		total = len(self._session_queue)
		done  = self._session_pos
		if total == 0:
			self.session_info_var.set("No session active")
		else:
			remaining = total - done
			self.session_info_var.set(
				f"{int(self._session_minutes)} min session  •  "
				f"{done}/{total} done  •  {remaining} remaining"
			)

	# ── Playback control ─────────────────────────────────────────────────

	def _on_select(self, _event: tk.Event) -> None:
		selection = self.listbox.curselection()
		if not selection:
			return
		self._play_index(int(selection[0]))

	def _play_index(self, index: int) -> None:
		if not self.files:
			return
		if index < 0 or index >= len(self.files):
			return
		self._end_handled_for_current_media = False

		# Save the score for whatever was playing before, then advance queue
		prev_name = self.files[self.current_index].name if self.files else None
		self._finalize_scorer()
		if prev_name:
			self._advance_session_pos(prev_name)

		self.current_index = index
		file_path = self.files[index]

		media = self.instance.media_new(str(file_path))
		self.player.set_media(media)
		self.player.play()
		self.status_var.set(f"Playing: {file_path.name}")
		self.play_pause_button.config(text="⏸ Pause")

		self.listbox.selection_clear(0, tk.END)
		self.listbox.selection_set(index)
		self.listbox.activate(index)

		# Start a fresh scorer for this video
		self._start_scorer(file_path.name)
		self._update_session_info()

	def play(self) -> None:
		if not self.files:
			return
		state = self.player.get_state()
		if state in (vlc.State.Paused, vlc.State.Stopped, vlc.State.Ended):
			self.player.play()
			self.status_var.set(f"Playing: {self.files[self.current_index].name}")
			self.play_pause_button.config(text="⏸ Pause")
			return
		if state == vlc.State.NothingSpecial:
			self._play_index(self.current_index)

	def pause(self) -> None:
		self.player.pause()
		if self.files:
			self.status_var.set(f"Paused: {self.files[self.current_index].name}")
			self.play_pause_button.config(text="▶ Play")

	def toggle_play_pause(self) -> None:
		if not self.files:
			return
		if self.player.get_state() == vlc.State.Playing:
			self.pause()
		else:
			self.play()

	def seek_relative(self, offset_ms: int) -> None:
		if not self.files:
			return
		current_ms = self.player.get_time()
		if current_ms < 0:
			current_ms = 0
		target_ms = current_ms + offset_ms
		length_ms = self.player.get_length()
		if length_ms > 0:
			target_ms = max(0, min(target_ms, length_ms))
		else:
			target_ms = max(0, target_ms)

		# Register backward seek as a rewind
		if offset_ms < 0 and self._scorer:
			self._scorer.register_rewind(current_ms, int(target_ms))
			self._update_rewind_display()

		self.player.set_time(int(target_ms))
		direction = "→ +10s" if offset_ms > 0 else "← −10s"
		self.status_var.set(
			f"{direction}  {self.files[self.current_index].name}  ({int(target_ms)//1000}s)"
		)

	def stop(self) -> None:
		self._end_handled_for_current_media = True
		self._finalize_scorer()
		self.player.stop()
		self.status_var.set("Stopped")
		self.play_pause_button.config(text="▶ Play")

	def play_next(self) -> None:
		if not self.files:
			return
		# Follow session queue if there is a next item, otherwise wrap around
		next_idx = self._next_session_index()
		if next_idx is None:
			# Session finished – wrap to beginning of file list
			next_idx = (self.current_index + 1) % len(self.files)
		self._play_index(next_idx)

	def play_previous(self) -> None:
		if not self.files:
			return
		self._play_index((self.current_index - 1) % len(self.files))

	def _on_close(self) -> None:
		try:
			self._finalize_scorer()
			self.player.stop()
		finally:
			self.root.destroy()


# ---------------------------------------------------------------------------
# Session-length dialog
# ---------------------------------------------------------------------------

def _ask_session_length(parent: tk.Tk | tk.Toplevel) -> float:
	"""
	Show a small modal dialog asking how many minutes the session should be.
	Returns the chosen number of minutes (float).  If the user cancels or
	enters something invalid, defaults to 30.0.
	"""
	dialog = tk.Toplevel(parent)
	dialog.withdraw()
	dialog.title("Session length")
	dialog.resizable(False, False)
	dialog.transient(parent)

	# Center on the screen (not relative to parent, which may still be blank/hidden)
	dw, dh = 340, 180
	sw = dialog.winfo_screenwidth()
	sh = dialog.winfo_screenheight()
	x = max(0, (sw - dw) // 2)
	y = max(0, (sh - dh) // 3)
	dialog.geometry(f"{dw}x{dh}+{x}+{y}")

	tk.Label(dialog, text="How long is today's practice session?",
			 font=("TkDefaultFont", 10, "bold")).pack(pady=(18, 6))

	presets_frame = tk.Frame(dialog)
	presets_frame.pack()

	result: list[float] = [30.0]

	def _choose(mins: float) -> None:
		result[0] = max(1.0, float(mins))
		dialog.grab_release()
		dialog.destroy()

	def _on_close() -> None:
		_choose(30.0)

	for label, mins in [("15 min", 15), ("30 min", 30), ("45 min", 45), ("60 min", 60)]:
		tk.Button(
			presets_frame, text=label, width=8,
			command=lambda m=mins: _choose(m),
		).pack(side=tk.LEFT, padx=4)

	custom_frame = tk.Frame(dialog)
	custom_frame.pack(pady=8)
	tk.Label(custom_frame, text="Custom:").pack(side=tk.LEFT)
	custom_var = tk.StringVar()
	custom_entry = tk.Entry(custom_frame, textvariable=custom_var, width=5)
	custom_entry.pack(side=tk.LEFT, padx=4)
	tk.Label(custom_frame, text="minutes").pack(side=tk.LEFT)
	tk.Button(
		custom_frame, text="Go",
		command=lambda: _choose(float(custom_var.get() or 30.0)),
	).pack(side=tk.LEFT, padx=4)

	def _on_custom_submit(_event: tk.Event | None = None) -> None:
		try:
			value = float(custom_var.get() or 30.0)
		except ValueError:
			value = 30.0
		_choose(value)

	custom_entry.bind("<Return>", _on_custom_submit)
	dialog.protocol("WM_DELETE_WINDOW", _on_close)

	# Make sure dialog is visible and focused above the blank root shell.
	dialog.deiconify()
	dialog.lift()
	dialog.attributes("-topmost", True)
	dialog.after(100, lambda: dialog.attributes("-topmost", False))
	dialog.focus_force()
	dialog.grab_set()

	parent.wait_window(dialog)
	return result[0]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
	root = tk.Tk()
	VideoPlayerApp(root, VIDEO_FOLDER)
	root.mainloop()


if __name__ == "__main__":
	main()
