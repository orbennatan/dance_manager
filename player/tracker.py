"""
Video session tracker and mastery scorer.

Each video file is tracked independently.  Every time the user completes a
viewing session the session count increases and a new mastery score is
computed.  The mastery score drives the spaced-repetition scheduler in
``scheduler.py``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Dict, Optional

class VideoRecord:
    """Holds tracking data for a single video file."""

    def __init__(
        self,
        filename: str,
        sessions: int = 0,
        mastery_score: float = 0.0,
        last_viewed: Optional[str] = None,
    ) -> None:
        self.filename = filename
        self.sessions = sessions
        self.mastery_score = mastery_score
        # ISO-8601 UTC timestamp or None
        self.last_viewed: Optional[str] = last_viewed

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "sessions": self.sessions,
            "mastery_score": self.mastery_score,
            "last_viewed": self.last_viewed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VideoRecord":
        return cls(
            filename=data["filename"],
            sessions=data.get("sessions", 0),
            mastery_score=data.get("mastery_score", 0.0),
            last_viewed=data.get("last_viewed"),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"VideoRecord(filename={self.filename!r}, "
            f"sessions={self.sessions}, "
            f"mastery_score={self.mastery_score:.2f})"
        )


def _compute_mastery(sessions: int) -> float:
    """
    Return a mastery score in [0, 1] that grows quickly at first and
    levels off as the session count increases.

    Uses the formula:  score = 1 - 1 / (1 + sessions / k)
    where k=3 controls how fast the score rises.

    Examples
    --------
    >>> _compute_mastery(0)
    0.0
    >>> round(_compute_mastery(3), 2)
    0.5
    >>> round(_compute_mastery(9), 2)
    0.75
    """
    k = 3.0
    return 1.0 - 1.0 / (1.0 + sessions / k)


class SessionTracker:
    """
    Persists and updates viewing session data for every video in the library.

    Parameters
    ----------
    data_file:
        Path to the JSON file used for persistence.  The directory must
        exist; the file is created on first save.
    """

    def __init__(self, data_file: str) -> None:
        self._data_file = data_file
        self._records: Dict[str, VideoRecord] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_session(self, filename: str) -> VideoRecord:
        """
        Record that the user has just completed a viewing session for
        *filename*.  The record is updated in memory; call :meth:`save`
        to persist.

        Parameters
        ----------
        filename:
            Basename of the video file (e.g. ``"samba.mp4"``).

        Returns
        -------
        VideoRecord
            The updated record.
        """
        record = self._get_or_create(filename)
        record.sessions += 1
        record.mastery_score = _compute_mastery(record.sessions)
        record.last_viewed = datetime.now(timezone.utc).isoformat()
        self.save()
        return record

    def get_record(self, filename: str) -> VideoRecord:
        """Return the record for *filename*, creating one if absent."""
        return self._get_or_create(filename)

    def all_records(self) -> list[VideoRecord]:
        """Return all tracked records."""
        return list(self._records.values())

    def register_videos(self, filenames: list[str]) -> None:
        """
        Ensure every video in *filenames* has a record.  Videos that are
        not yet tracked are added with zero sessions.
        """
        for name in filenames:
            self._get_or_create(name)
        self.save()

    def save(self) -> None:
        """Persist the current state to the data file."""
        data = [r.to_dict() for r in self._records.values()]
        with open(self._data_file, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, filename: str) -> VideoRecord:
        if filename not in self._records:
            self._records[filename] = VideoRecord(filename)
        return self._records[filename]

    def _load(self) -> None:
        if not os.path.exists(self._data_file):
            return
        try:
            with open(self._data_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for item in data:
                record = VideoRecord.from_dict(item)
                self._records[record.filename] = record
        except (json.JSONDecodeError, KeyError):
            # Corrupted file – start fresh but keep the old file as backup
            backup = self._data_file + ".bak"
            if os.path.exists(self._data_file):
                os.replace(self._data_file, backup)
