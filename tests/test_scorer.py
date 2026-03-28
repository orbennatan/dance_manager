"""Tests for the session scorer (scorer.py)."""

import pytest

from scorer import EMA_ALPHA, MAX_PENALTY_PER_REWIND, SessionScorer


VIDEO_3MIN = 180_000   # ms


# ---------------------------------------------------------------------------
# start / reset
# ---------------------------------------------------------------------------

def test_scorer_not_started_returns_unchanged_historical():
    sc = SessionScorer(filename="x.mp4")
    r = sc.finalize()
    # No start() called – historical should stay at the default 0.0
    assert r.new_historical == 0.0
    assert r.rewind_count == 0


def test_reset_clears_state():
    sc = SessionScorer(filename="x.mp4")
    sc.start(VIDEO_3MIN, 50.0)
    sc.register_rewind(60_000, 0)
    sc.reset()
    r = sc.finalize()
    assert r.new_historical == 0.0
    assert r.rewind_count == 0


# ---------------------------------------------------------------------------
# Perfect session (no rewinds)
# ---------------------------------------------------------------------------

def test_perfect_session_score_is_100():
    sc = SessionScorer(filename="samba.mp4")
    sc.start(VIDEO_3MIN, 0.0)
    r = sc.finalize()
    assert r.session_score == 100.0


def test_ema_first_perfect_session():
    """First perfect play of a new dance: 0.3*100 + 0.7*0 = 30."""
    sc = SessionScorer(filename="samba.mp4")
    sc.start(VIDEO_3MIN, 0.0)
    r = sc.finalize()
    assert r.new_historical == pytest.approx(30.0)


def test_ema_progresses_toward_promotion():
    """Three perfect sessions should push score above 60 (Pool A → B boundary)."""
    score = 0.0
    for _ in range(3):
        sc = SessionScorer(filename="waltz.mp4")
        sc.start(VIDEO_3MIN, score)
        r = sc.finalize()
        score = r.new_historical
    # Expected: 0→30→51→65.7
    assert score > 60.0, f"Expected > 60 after 3 perfect sessions, got {score}"


# ---------------------------------------------------------------------------
# Rewind penalties
# ---------------------------------------------------------------------------

def test_rewind_reduces_score():
    sc = SessionScorer(filename="tango.mp4")
    sc.start(VIDEO_3MIN, 0.0)
    sc.register_rewind(from_ms=90_000, to_ms=30_000)  # 60 s back
    r = sc.finalize()
    assert r.session_score < 100.0
    assert r.rewind_count == 1


def test_forward_seek_is_ignored():
    sc = SessionScorer(filename="tango.mp4")
    sc.start(VIDEO_3MIN, 0.0)
    sc.register_rewind(from_ms=30_000, to_ms=90_000)  # forward – not a rewind
    r = sc.finalize()
    assert r.session_score == 100.0
    assert r.rewind_count == 0


def test_zero_distance_seek_is_ignored():
    sc = SessionScorer(filename="tango.mp4")
    sc.start(VIDEO_3MIN, 0.0)
    sc.register_rewind(50_000, 50_000)
    r = sc.finalize()
    assert r.session_score == 100.0


def test_score_never_goes_negative():
    sc = SessionScorer(filename="chacha.mp4")
    sc.start(VIDEO_3MIN, 0.0)
    for _ in range(20):  # many large rewinds
        sc.register_rewind(180_000, 0)
    r = sc.finalize()
    assert r.session_score >= 0.0


def test_penalty_proportional_to_distance():
    """A 50 % scrub-back should cost more than a 5 % scrub-back."""
    sc_big = SessionScorer(filename="a.mp4")
    sc_big.start(VIDEO_3MIN, 0.0)
    sc_big.register_rewind(180_000, 90_000)   # 50 % of 3 min

    sc_small = SessionScorer(filename="b.mp4")
    sc_small.start(VIDEO_3MIN, 0.0)
    sc_small.register_rewind(20_000, 11_000)  # ~5 %

    r_big = sc_big.finalize()
    r_small = sc_small.finalize()
    assert r_big.session_score < r_small.session_score


def test_rewind_without_known_length_applies_flat_penalty():
    sc = SessionScorer(filename="x.mp4")
    sc.start(video_length_ms=0, old_historical_score=0.0)  # length unknown
    sc.register_rewind(50_000, 10_000)
    r = sc.finalize()
    assert r.total_penalty == pytest.approx(MAX_PENALTY_PER_REWIND)


# ---------------------------------------------------------------------------
# EMA with heavy rewinds (score should decrease / stay in Pool A)
# ---------------------------------------------------------------------------

def test_heavy_rewind_keeps_score_in_pool_a():
    """A session with a big rewind on a dance already at score 51 keeps it < 60."""
    sc = SessionScorer(filename="foxtrot.mp4")
    sc.start(VIDEO_3MIN, old_historical_score=51.0)
    sc.register_rewind(180_000, 0)   # scrub back to start
    r = sc.finalize()
    assert r.new_historical < 60.0, (
        f"Expected score < 60 (stay Pool A) after big rewind, got {r.new_historical}"
    )
