"""
Spaced-repetition scheduler for the dance video library.

Each video is assigned a *priority* based on how overdue it is for review.
Videos with lower mastery scores and/or those not seen recently are given
higher priority and therefore appear more frequently.

Algorithm
---------
1. Compute the *review interval* for each video (in hours):

       interval_hours = BASE_INTERVAL_HOURS * DIFFICULTY_FACTOR ** mastery_score

   Where BASE_INTERVAL_HOURS = 1 and DIFFICULTY_FACTOR = 48.
   This means:
     * mastery = 0.0  → interval ≈ 1 hour  (needs lots of practice)
     * mastery = 0.5  → interval ≈ 7 hours
     * mastery = 1.0  → interval = 48 hours (well mastered)

2. Compute *overdue_hours* = hours since last view − review interval.
   A positive value means the video is overdue.

3. Videos are sorted by *overdue_hours* descending; the most overdue video
   is suggested first.

4. For videos never seen before ``last_viewed`` is ``None``; they are
   considered maximally overdue so they are always suggested first.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import List, Optional

from .tracker import VideoRecord

# How long (in hours) a perfectly mastered video should wait between reviews
DIFFICULTY_FACTOR: float = 48.0
# Minimum review interval in hours (for a mastery score of 0)
BASE_INTERVAL_HOURS: float = 1.0


def review_interval_hours(mastery_score: float) -> float:
    """
    Return the recommended review interval (in hours) for a given mastery
    score in [0, 1].

    >>> review_interval_hours(0.0)
    1.0
    >>> round(review_interval_hours(1.0), 1)
    48.0
    """
    return BASE_INTERVAL_HOURS * (DIFFICULTY_FACTOR ** mastery_score)


def overdue_hours(record: VideoRecord, now: Optional[datetime] = None) -> float:
    """
    Return how many hours *overdue* the video is.

    A positive result means the video is overdue; a negative result means
    it was reviewed recently and can wait.

    Videos that have never been viewed are treated as maximally overdue
    (``float("inf")``).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if record.last_viewed is None:
        return float("inf")
    last = datetime.fromisoformat(record.last_viewed)
    elapsed = (now - last).total_seconds() / 3600.0
    interval = review_interval_hours(record.mastery_score)
    return elapsed - interval


def prioritize(records: List[VideoRecord], now: Optional[datetime] = None) -> List[VideoRecord]:
    """
    Return *records* sorted from highest priority (most overdue) to lowest.

    Parameters
    ----------
    records:
        List of :class:`~player.tracker.VideoRecord` objects to rank.
    now:
        Reference time for overdue calculation; defaults to current UTC time.

    Returns
    -------
    list[VideoRecord]
        A new list sorted by descending overdue_hours.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    def _key(r: VideoRecord) -> float:
        od = overdue_hours(r, now=now)
        # Replace inf with a large finite number for stable sorting
        return od if math.isfinite(od) else 1e18

    return sorted(records, key=_key, reverse=True)


def next_video(records: List[VideoRecord], now: Optional[datetime] = None) -> Optional[VideoRecord]:
    """
    Return the single highest-priority video to play next, or ``None`` if
    *records* is empty.

    Parameters
    ----------
    records:
        All available video records.
    now:
        Reference time; defaults to current UTC time.
    """
    ordered = prioritize(records, now=now)
    return ordered[0] if ordered else None
