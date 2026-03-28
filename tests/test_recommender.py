"""Tests for the recommendation engine (recommender.py)."""

from datetime import datetime, timezone

import pytest

from db import DanceStat
from recommender import (
    POOL_A_MAX,
    POOL_B_MAX,
    build_session,
    pool_label,
    split_into_pools,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _stat(filename: str, score: float, last_played: datetime | None = None, play_count: int = 3) -> DanceStat:
    return DanceStat(id=1, filename=filename, play_count=play_count,
                     historical_score=score, last_played=last_played)


ALL_FILES = {"a.mp4", "b.mp4", "c.mp4", "d.mp4", "e.mp4"}


# ---------------------------------------------------------------------------
# pool_label
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,expected", [
    (0.0,   "A – Learning"),
    (59.99, "A – Learning"),
    (60.0,  "B – Familiar"),
    (84.99, "B – Familiar"),
    (85.0,  "C – Mastered"),
    (100.0, "C – Mastered"),
])
def test_pool_label(score, expected):
    assert pool_label(score) == expected


# ---------------------------------------------------------------------------
# split_into_pools – correctness
# ---------------------------------------------------------------------------

def test_new_dance_in_pool_a():
    stats = [_stat("new.mp4", 0.0, play_count=0)]
    a, b, c = split_into_pools(stats, {"new.mp4"})
    assert len(a) == 1
    assert len(b) == 0
    assert len(c) == 0


def test_score_59_in_pool_a():
    a, b, c = split_into_pools([_stat("x.mp4", 59.0)], {"x.mp4"})
    assert len(a) == 1 and len(b) == 0


def test_score_60_in_pool_b():
    a, b, c = split_into_pools([_stat("x.mp4", 60.0)], {"x.mp4"})
    assert len(b) == 1 and len(a) == 0


def test_score_85_in_pool_c():
    a, b, c = split_into_pools([_stat("x.mp4", 85.0)], {"x.mp4"})
    assert len(c) == 1 and len(b) == 0


def test_unavailable_files_excluded():
    stats = [_stat("a.mp4", 10.0), _stat("b.mp4", 20.0)]
    a, b, c = split_into_pools(stats, {"a.mp4"})   # b.mp4 not on disk
    assert all(s.filename != "b.mp4" for s in a)


# ---------------------------------------------------------------------------
# split_into_pools – sort order
# ---------------------------------------------------------------------------

def test_pool_a_sorted_lowest_score_first():
    stats = [_stat("high.mp4", 50.0), _stat("low.mp4", 5.0), _stat("mid.mp4", 30.0)]
    a, _, _ = split_into_pools(stats, {"high.mp4", "low.mp4", "mid.mp4"})
    scores = [s.historical_score for s in a]
    assert scores == sorted(scores)


def test_pool_a_new_dance_comes_first():
    """Score 0.0 (new dance) must be first in Pool A."""
    stats = [_stat("learning.mp4", 45.0), _stat("new.mp4", 0.0, play_count=0)]
    a, _, _ = split_into_pools(stats, {"learning.mp4", "new.mp4"})
    assert a[0].filename == "new.mp4"


def test_pool_b_sorted_least_recently_played():
    stats = [
        _stat("recent.mp4",  70.0, last_played=_dt(2026, 3, 27)),
        _stat("old.mp4",     70.0, last_played=_dt(2025, 1, 1)),
        _stat("never.mp4",   70.0, last_played=None),
    ]
    _, b, _ = split_into_pools(stats, {"recent.mp4", "old.mp4", "never.mp4"})
    # "never" treated as oldest → first
    assert b[0].filename == "never.mp4"
    assert b[1].filename == "old.mp4"
    assert b[2].filename == "recent.mp4"


def test_pool_c_sorted_oldest_last_played():
    stats = [
        _stat("new_master.mp4",  90.0, last_played=_dt(2026, 3, 25)),
        _stat("old_master.mp4",  90.0, last_played=_dt(2024, 6, 1)),
    ]
    _, _, c = split_into_pools(stats, {"new_master.mp4", "old_master.mp4"})
    assert c[0].filename == "old_master.mp4"


# ---------------------------------------------------------------------------
# build_session
# ---------------------------------------------------------------------------

def _mixed_stats() -> list[DanceStat]:
    return [
        _stat("a1.mp4", 0.0,  play_count=0),   # Pool A – new
        _stat("a2.mp4", 30.0),                  # Pool A
        _stat("a3.mp4", 50.0),                  # Pool A
        _stat("b1.mp4", 65.0, _dt(2026,1,1)),   # Pool B
        _stat("b2.mp4", 75.0, _dt(2026,2,1)),   # Pool B
        _stat("c1.mp4", 90.0, _dt(2025,6,1)),   # Pool C
    ]


_ALL = {s.filename for s in _mixed_stats()}


def test_session_respects_total_slot_count():
    stats = _mixed_stats()
    # 12 min / 3 min per video = 4 slots
    session = build_session(stats, _ALL, session_minutes=12, avg_video_minutes=3)
    assert len(session) <= 4


def test_session_no_duplicates():
    session = build_session(_mixed_stats(), _ALL, session_minutes=30)
    assert len(session) == len(set(session))


def test_session_pool_a_comes_first():
    session = build_session(_mixed_stats(), _ALL, session_minutes=30)
    # find first Pool-B / Pool-C video position
    pool_a_names = {"a1.mp4", "a2.mp4", "a3.mp4"}
    pool_b_c_positions = [i for i, f in enumerate(session) if f not in pool_a_names]
    pool_a_positions   = [i for i, f in enumerate(session) if f in pool_a_names]
    if pool_a_positions and pool_b_c_positions:
        assert max(pool_a_positions) < max(pool_b_c_positions) or \
               min(pool_a_positions) < min(pool_b_c_positions)


def test_session_works_with_only_pool_a():
    stats = [_stat("x.mp4", 0.0), _stat("y.mp4", 40.0)]
    session = build_session(stats, {"x.mp4", "y.mp4"}, session_minutes=9)
    assert set(session).issubset({"x.mp4", "y.mp4"})


def test_session_empty_when_no_files():
    session = build_session([], set(), session_minutes=30)
    assert session == []


def test_session_excludes_missing_files():
    stats = _mixed_stats()
    avail = {"a1.mp4"}   # only one file on disk
    session = build_session(stats, avail, session_minutes=30)
    assert all(f == "a1.mp4" for f in session)
