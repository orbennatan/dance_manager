"""Tests for player.scheduler"""

from datetime import datetime, timedelta, timezone

import pytest

from player.scheduler import (
    BASE_INTERVAL_HOURS,
    DIFFICULTY_FACTOR,
    next_video,
    overdue_hours,
    prioritize,
    review_interval_hours,
)
from player.tracker import VideoRecord


# ---------------------------------------------------------------------------
# review_interval_hours
# ---------------------------------------------------------------------------

class TestReviewIntervalHours:
    def test_zero_mastery_equals_base_interval(self):
        assert review_interval_hours(0.0) == BASE_INTERVAL_HOURS

    def test_full_mastery_equals_difficulty_factor(self):
        assert review_interval_hours(1.0) == pytest.approx(DIFFICULTY_FACTOR)

    def test_interval_increases_with_mastery(self):
        scores = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        intervals = [review_interval_hours(s) for s in scores]
        assert intervals == sorted(intervals)


# ---------------------------------------------------------------------------
# overdue_hours
# ---------------------------------------------------------------------------

NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


class TestOverdueHours:
    def test_never_viewed_is_infinite(self):
        r = VideoRecord("a.mp4")
        assert overdue_hours(r, now=NOW) == float("inf")

    def test_just_viewed_zero_mastery_is_negative(self):
        # Viewed exactly now → elapsed = 0 → overdue = 0 - BASE_INTERVAL < 0
        r = VideoRecord("a.mp4", sessions=1, mastery_score=0.0, last_viewed=NOW.isoformat())
        od = overdue_hours(r, now=NOW)
        assert od == pytest.approx(-BASE_INTERVAL_HOURS)

    def test_overdue_video(self):
        # Viewed 10 hours ago; mastery=0 → interval=1 → overdue=9
        past = NOW - timedelta(hours=10)
        r = VideoRecord("a.mp4", sessions=3, mastery_score=0.0, last_viewed=past.isoformat())
        od = overdue_hours(r, now=NOW)
        assert od == pytest.approx(10 - BASE_INTERVAL_HOURS)

    def test_not_yet_due(self):
        # Viewed 1 hour ago; mastery=1.0 → interval=48 → overdue negative
        past = NOW - timedelta(hours=1)
        r = VideoRecord("a.mp4", sessions=20, mastery_score=1.0, last_viewed=past.isoformat())
        od = overdue_hours(r, now=NOW)
        assert od < 0


# ---------------------------------------------------------------------------
# prioritize
# ---------------------------------------------------------------------------

class TestPrioritize:
    def _make_record(self, name, sessions=0, mastery=0.0, hours_ago=None):
        last = None
        if hours_ago is not None:
            last = (NOW - timedelta(hours=hours_ago)).isoformat()
        return VideoRecord(name, sessions=sessions, mastery_score=mastery, last_viewed=last)

    def test_never_viewed_comes_first(self):
        r_new = self._make_record("new.mp4")
        r_old = self._make_record("old.mp4", sessions=5, mastery=0.5, hours_ago=100)
        result = prioritize([r_old, r_new], now=NOW)
        assert result[0].filename == "new.mp4"

    def test_high_mastery_comes_last(self):
        r_low = self._make_record("low.mp4", sessions=1, mastery=0.1, hours_ago=10)
        r_high = self._make_record("high.mp4", sessions=20, mastery=0.9, hours_ago=10)
        result = prioritize([r_high, r_low], now=NOW)
        assert result[0].filename == "low.mp4"
        assert result[-1].filename == "high.mp4"

    def test_empty_list(self):
        assert prioritize([], now=NOW) == []

    def test_returns_all_records(self):
        records = [self._make_record(f"{i}.mp4") for i in range(5)]
        result = prioritize(records, now=NOW)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# next_video
# ---------------------------------------------------------------------------

class TestNextVideo:
    def test_returns_none_for_empty_list(self):
        assert next_video([], now=NOW) is None

    def test_returns_single_record(self):
        r = VideoRecord("only.mp4")
        assert next_video([r], now=NOW) is r

    def test_returns_most_overdue(self):
        past_10 = (NOW - timedelta(hours=10)).isoformat()
        past_100 = (NOW - timedelta(hours=100)).isoformat()
        r_recent = VideoRecord("recent.mp4", mastery_score=0.0, last_viewed=past_10)
        r_old = VideoRecord("old.mp4", mastery_score=0.0, last_viewed=past_100)
        result = next_video([r_recent, r_old], now=NOW)
        assert result.filename == "old.mp4"
