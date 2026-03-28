"""Tests for the database layer (db.py)."""

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

import db


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """A fresh, isolated database for each test."""
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

def test_init_creates_table(tmp_db):
    import sqlite3
    con = sqlite3.connect(str(tmp_db))
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dance_stats'"
    ).fetchall()
    con.close()
    assert len(rows) == 1


def test_init_idempotent(tmp_db):
    """Calling init_db again on the same file must not raise."""
    db.init_db(tmp_db)


# ---------------------------------------------------------------------------
# get_or_create – Zero-Trust Initialization
# ---------------------------------------------------------------------------

def test_new_dance_starts_at_zero(tmp_db):
    stat = db.get_or_create("samba.mp4", tmp_db)
    assert stat.historical_score == 0.0
    assert stat.play_count == 0
    assert stat.last_played is None


def test_get_or_create_is_idempotent(tmp_db):
    s1 = db.get_or_create("waltz.mp4", tmp_db)
    s2 = db.get_or_create("waltz.mp4", tmp_db)
    assert s1.id == s2.id
    assert s1.historical_score == s2.historical_score


def test_different_files_get_separate_rows(tmp_db):
    a = db.get_or_create("a.mp4", tmp_db)
    b = db.get_or_create("b.mp4", tmp_db)
    assert a.id != b.id


# ---------------------------------------------------------------------------
# update_score
# ---------------------------------------------------------------------------

def test_update_score_persists(tmp_db):
    db.get_or_create("tango.mp4", tmp_db)
    s = db.update_score("tango.mp4", 42.5, tmp_db)
    assert s.historical_score == 42.5


def test_update_increments_play_count(tmp_db):
    db.get_or_create("tango.mp4", tmp_db)
    db.update_score("tango.mp4", 10.0, tmp_db)
    db.update_score("tango.mp4", 20.0, tmp_db)
    s = db.get_stat("tango.mp4", tmp_db)
    assert s.play_count == 2


def test_update_sets_last_played(tmp_db):
    before = datetime.now(tz=timezone.utc)
    db.get_or_create("fox.mp4", tmp_db)
    s = db.update_score("fox.mp4", 50.0, tmp_db)
    assert s.last_played is not None
    assert s.last_played >= before


def test_score_clamped_to_four_decimals(tmp_db):
    db.get_or_create("x.mp4", tmp_db)
    s = db.update_score("x.mp4", 33.33333333, tmp_db)
    assert s.historical_score == round(33.33333333, 4)


# ---------------------------------------------------------------------------
# get_all / get_stat
# ---------------------------------------------------------------------------

def test_get_all_returns_all(tmp_db):
    for name in ["a.mp4", "b.mp4", "c.mp4"]:
        db.get_or_create(name, tmp_db)
    all_stats = db.get_all(tmp_db)
    assert len(all_stats) == 3


def test_get_stat_missing_returns_none(tmp_db):
    assert db.get_stat("ghost.mp4", tmp_db) is None
