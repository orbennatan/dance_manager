"""
Dance Manager – Recommendation Engine
======================================
Implements the three-pool spaced-repetition scheduler.

Pool Definitions
----------------
Pool A – Learning   scores  0 – 59   → 60 % of session time
Pool B – Familiar   scores 60 – 84   → 25 % of session time
Pool C – Mastered   scores 85 – 100  → 15 % of session time

Prioritisation within each pool
--------------------------------
Pool A: lowest historical_score first  (brand-new dances score 0 → top of queue)
Pool B: least recently played first    (NULL last_played treated as "never")
Pool C: oldest last_played timestamp first (NULL treated as "never")

Session building
----------------
`build_session(stats, available_filenames, session_minutes)` returns an
ordered list of filenames that fills the requested session time using the
pool allocations above.  Each video is assumed to be ~3 minutes long by
default; pass `avg_video_minutes` to override.

The function never repeats a video within the same session.
If a pool doesn't have enough material to fill its quota, the remaining
time is distributed proportionally to the other pools.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Sequence

from db import DanceStat

# ---------------------------------------------------------------------------
# Pool thresholds
# ---------------------------------------------------------------------------

POOL_A_MAX = 59.9999   # score < 60  → Pool A
POOL_B_MAX = 84.9999   # score < 85  → Pool B
                       # score >= 85 → Pool C

POOL_A_SHARE = 0.60
POOL_B_SHARE = 0.25
POOL_C_SHARE = 0.15

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _last_played_key(stat: DanceStat) -> datetime:
    """Sort key: None → treated as the Unix epoch (oldest possible)."""
    return stat.last_played if stat.last_played is not None else _EPOCH


# ---------------------------------------------------------------------------
# Pool splitting
# ---------------------------------------------------------------------------


def split_into_pools(
    stats: Sequence[DanceStat],
    available_filenames: set[str],
) -> tuple[list[DanceStat], list[DanceStat], list[DanceStat]]:
    """
    Partition *stats* into (pool_a, pool_b, pool_c), keeping only entries
    whose filename appears in *available_filenames* (i.e. the file still exists
    on disk).

    Returns three lists already sorted according to the pool priorities.
    """
    available = [s for s in stats if s.filename in available_filenames]

    pool_a = sorted(
        [s for s in available if s.historical_score <= POOL_A_MAX],
        key=lambda s: s.historical_score,          # lowest first
    )
    pool_b = sorted(
        [s for s in available if POOL_A_MAX < s.historical_score <= POOL_B_MAX],
        key=_last_played_key,                       # least recently played first
    )
    pool_c = sorted(
        [s for s in available if s.historical_score > POOL_B_MAX],
        key=_last_played_key,                       # oldest last_played first
    )

    return pool_a, pool_b, pool_c


# ---------------------------------------------------------------------------
# Session builder
# ---------------------------------------------------------------------------


def build_session(
    stats: Sequence[DanceStat],
    available_filenames: set[str],
    session_minutes: float = 30.0,
    avg_video_minutes: float = 3.0,
) -> list[str]:
    """
    Return an ordered list of filenames to play in a single session.

    Parameters
    ----------
    stats:
        All rows from the database (from db.get_all()).
    available_filenames:
        Set of filenames that currently exist on disk.
    session_minutes:
        Total desired session length in minutes.
    avg_video_minutes:
        Assumed average length per video (used for slot calculations).

    Returns
    -------
    List of filenames in recommended play order.
    Pool A first (lowest score), then Pool B, then Pool C.
    """
    if avg_video_minutes <= 0:
        avg_video_minutes = 3.0

    total_slots = max(1, math.ceil(session_minutes / avg_video_minutes))

    pool_a, pool_b, pool_c = split_into_pools(stats, available_filenames)

    # Ideal slot counts per pool
    slots_a = round(total_slots * POOL_A_SHARE)
    slots_b = round(total_slots * POOL_B_SHARE)
    slots_c = total_slots - slots_a - slots_b  # remainder to avoid rounding drift

    # Clamp to available items
    slots_a = min(slots_a, len(pool_a))
    slots_b = min(slots_b, len(pool_b))
    slots_c = min(slots_c, len(pool_c))

    # Redistribute unused quota proportionally
    deficit = total_slots - slots_a - slots_b - slots_c
    if deficit > 0:
        # Try to fill from whichever pools still have items
        extras = _redistribute(deficit, pool_a, pool_b, pool_c, slots_a, slots_b, slots_c)
        slots_a, slots_b, slots_c = extras

    chosen: list[str] = []
    chosen += [s.filename for s in pool_a[:slots_a]]
    chosen += [s.filename for s in pool_b[:slots_b]]
    chosen += [s.filename for s in pool_c[:slots_c]]

    return chosen


def _redistribute(
    deficit: int,
    pool_a: list[DanceStat],
    pool_b: list[DanceStat],
    pool_c: list[DanceStat],
    slots_a: int,
    slots_b: int,
    slots_c: int,
) -> tuple[int, int, int]:
    """Fill any remaining slots from pools that still have capacity."""
    cap_a = len(pool_a) - slots_a
    cap_b = len(pool_b) - slots_b
    cap_c = len(pool_c) - slots_c

    # Refill in priority order: A → B → C
    for cap, attr in [(cap_a, "a"), (cap_b, "b"), (cap_c, "c")]:
        take = min(deficit, cap)
        if attr == "a":
            slots_a += take
        elif attr == "b":
            slots_b += take
        else:
            slots_c += take
        deficit -= take
        if deficit == 0:
            break

    return slots_a, slots_b, slots_c


# ---------------------------------------------------------------------------
# Pool label helper (used by the UI)
# ---------------------------------------------------------------------------


def pool_label(score: float) -> str:
    """Return a human-readable pool label for *score*."""
    if score <= POOL_A_MAX:
        return "A – Learning"
    if score <= POOL_B_MAX:
        return "B – Familiar"
    return "C – Mastered"
