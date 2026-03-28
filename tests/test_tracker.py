"""Tests for player.tracker"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from player.tracker import SessionTracker, VideoRecord, _compute_mastery


# ---------------------------------------------------------------------------
# _compute_mastery
# ---------------------------------------------------------------------------

class TestComputeMastery:
    def test_zero_sessions_gives_zero(self):
        assert _compute_mastery(0) == 0.0

    def test_score_increases_with_sessions(self):
        scores = [_compute_mastery(n) for n in range(10)]
        assert scores == sorted(scores), "score should be monotonically increasing"

    def test_score_never_reaches_one(self):
        assert _compute_mastery(1_000_000) < 1.0

    def test_score_at_k_sessions_is_half(self):
        # k = 3 → score(3) = 0.5
        assert round(_compute_mastery(3), 6) == pytest.approx(0.5)

    def test_score_bounded_zero_to_one(self):
        for n in range(50):
            s = _compute_mastery(n)
            assert 0.0 <= s < 1.0


# ---------------------------------------------------------------------------
# VideoRecord
# ---------------------------------------------------------------------------

class TestVideoRecord:
    def test_defaults(self):
        r = VideoRecord("foo.mp4")
        assert r.sessions == 0
        assert r.mastery_score == 0.0
        assert r.last_viewed is None

    def test_round_trip(self):
        r = VideoRecord("bar.mp4", sessions=5, mastery_score=0.625, last_viewed="2024-01-01T00:00:00+00:00")
        r2 = VideoRecord.from_dict(r.to_dict())
        assert r2.filename == r.filename
        assert r2.sessions == r.sessions
        assert r2.mastery_score == r.mastery_score
        assert r2.last_viewed == r.last_viewed


# ---------------------------------------------------------------------------
# SessionTracker
# ---------------------------------------------------------------------------

class TestSessionTracker:
    @pytest.fixture()
    def tracker(self, tmp_path):
        return SessionTracker(str(tmp_path / "data.json"))

    def test_record_session_increments_count(self, tracker):
        rec = tracker.record_session("tango.mp4")
        assert rec.sessions == 1

    def test_record_session_updates_mastery(self, tracker):
        rec = tracker.record_session("tango.mp4")
        assert rec.mastery_score > 0.0

    def test_record_session_sets_last_viewed(self, tracker):
        before = datetime.now(timezone.utc)
        rec = tracker.record_session("tango.mp4")
        after = datetime.now(timezone.utc)
        ts = datetime.fromisoformat(rec.last_viewed)
        assert before <= ts <= after

    def test_multiple_sessions_accumulate(self, tracker):
        for _ in range(5):
            tracker.record_session("samba.mp4")
        rec = tracker.get_record("samba.mp4")
        assert rec.sessions == 5

    def test_persistence(self, tmp_path):
        path = str(tmp_path / "data.json")
        t1 = SessionTracker(path)
        t1.record_session("waltz.mp4")

        t2 = SessionTracker(path)
        rec = t2.get_record("waltz.mp4")
        assert rec.sessions == 1

    def test_register_videos_creates_zero_records(self, tracker):
        tracker.register_videos(["a.mp4", "b.mp4"])
        assert tracker.get_record("a.mp4").sessions == 0
        assert tracker.get_record("b.mp4").sessions == 0

    def test_all_records_returns_all(self, tracker):
        tracker.register_videos(["a.mp4", "b.mp4", "c.mp4"])
        assert len(tracker.all_records()) == 3

    def test_corrupted_file_starts_fresh(self, tmp_path):
        path = str(tmp_path / "data.json")
        with open(path, "w") as f:
            f.write("not valid json{{")
        tracker = SessionTracker(path)
        # Should start with an empty record set; no exception raised
        assert tracker.all_records() == []

    def test_save_creates_valid_json(self, tmp_path):
        path = str(tmp_path / "data.json")
        tracker = SessionTracker(path)
        tracker.record_session("foxtrot.mp4")
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert data[0]["filename"] == "foxtrot.mp4"
