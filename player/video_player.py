"""
Video playback helper.

Opens a video file using the best available media player found on the
current system.  The call is *blocking*: it returns only after the
player process exits, which lets the caller record a completed session.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Optional

# Preferred player commands in priority order (Linux / macOS / Windows)
_LINUX_PLAYERS = ["mpv", "vlc", "cvlc", "totem", "mplayer", "ffplay"]
_MAC_PLAYERS = ["mpv", "vlc", "iina", "ffplay"]
_WINDOWS_PLAYERS = ["mpv", "vlc", "ffplay"]


def _find_player() -> Optional[str]:
    """Return the path to the first usable media player, or ``None``."""
    system = platform.system()
    if system == "Linux":
        candidates = _LINUX_PLAYERS
    elif system == "Darwin":
        candidates = _MAC_PLAYERS
    else:
        candidates = _WINDOWS_PLAYERS
    for cmd in candidates:
        if shutil.which(cmd):
            return cmd
    return None


def play(filepath: str, player: Optional[str] = None) -> None:
    """
    Play *filepath* using a media player and block until it exits.

    Parameters
    ----------
    filepath:
        Absolute path to the video file.
    player:
        Override the auto-detected player command.

    Raises
    ------
    FileNotFoundError
        If *filepath* does not exist.
    RuntimeError
        If no suitable media player can be found on the system.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Video file not found: {filepath}")

    cmd = player or _find_player()
    if cmd is None:
        # Fall back to the OS default handler (non-blocking on some systems)
        _open_with_default(filepath)
        return

    subprocess.run([cmd, filepath], check=False)


def _open_with_default(filepath: str) -> None:
    """Open *filepath* with the OS default application (best-effort)."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", filepath], check=False)
        elif system == "Windows":
            os.startfile(filepath)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", filepath], check=False)
    except Exception:
        pass
