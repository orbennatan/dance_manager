"""
Dance Manager – Database Layer
================================
Manages a local SQLite database that persists per-video statistics.

Schema (table: dance_stats)
---------------------------
id               INTEGER  PRIMARY KEY AUTOINCREMENT
filename         TEXT     UNIQUE NOT NULL   – bare filename, e.g. "samba.mp4"
play_count       INTEGER  NOT NULL DEFAULT 0
historical_score REAL     NOT NULL DEFAULT 0.0
last_played      TEXT     NULL              – ISO-8601 datetime string

Zero-Trust Initialization
-------------------------
Any video file not yet seen by the database is inserted with
  historical_score = 0.0   (places it immediately into Pool A)
  play_count       = 0
  last_played      = NULL
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, NamedTuple

# Default database location – same directory as this module.
_DEFAULT_DB_PATH = Path(__file__).parent / "dance_stats.db"


class DanceStat(NamedTuple):
    """Immutable snapshot of a single row from the dance_stats table."""

    id: int
    filename: str
    play_count: int
    historical_score: float
    last_played: datetime | None  # tz-aware UTC, or None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a connection that automatically commits or rolls back."""
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _row_to_stat(row: sqlite3.Row) -> DanceStat:
    last_played: datetime | None = None
    if row["last_played"] is not None:
        try:
            last_played = datetime.fromisoformat(row["last_played"]).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            last_played = None
    return DanceStat(
        id=row["id"],
        filename=row["filename"],
        play_count=row["play_count"],
        historical_score=float(row["historical_score"]),
        last_played=last_played,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_db(db_path: Path = _DEFAULT_DB_PATH) -> None:
    """Create the database and table if they do not already exist."""
    with _connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS dance_stats (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                filename         TEXT    UNIQUE NOT NULL,
                play_count       INTEGER NOT NULL DEFAULT 0,
                historical_score REAL    NOT NULL DEFAULT 0.0,
                last_played      TEXT    NULL
            )
            """
        )


def get_or_create(filename: str, db_path: Path = _DEFAULT_DB_PATH) -> DanceStat:
    """
    Return the stats for *filename*, creating a zero-trust entry if absent.

    "Zero-trust" means new dances start with:
      historical_score = 0.0  → lands in Pool A immediately
      play_count       = 0
      last_played      = NULL
    """
    with _connect(db_path) as con:
        con.execute(
            """
            INSERT OR IGNORE INTO dance_stats (filename, play_count, historical_score, last_played)
            VALUES (?, 0, 0.0, NULL)
            """,
            (filename,),
        )
        row = con.execute(
            "SELECT * FROM dance_stats WHERE filename = ?", (filename,)
        ).fetchone()
    return _row_to_stat(row)


def update_score(
    filename: str,
    new_historical_score: float,
    db_path: Path = _DEFAULT_DB_PATH,
) -> DanceStat:
    """
    Persist a new historical score for *filename* and increment play_count.
    Also stamps last_played with the current UTC time.
    """
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    with _connect(db_path) as con:
        con.execute(
            """
            UPDATE dance_stats
               SET historical_score = ?,
                   play_count       = play_count + 1,
                   last_played      = ?
             WHERE filename = ?
            """,
            (round(float(new_historical_score), 4), now_iso, filename),
        )
        row = con.execute(
            "SELECT * FROM dance_stats WHERE filename = ?", (filename,)
        ).fetchone()
    return _row_to_stat(row)


def get_all(db_path: Path = _DEFAULT_DB_PATH) -> list[DanceStat]:
    """Return all rows ordered by filename."""
    with _connect(db_path) as con:
        rows = con.execute(
            "SELECT * FROM dance_stats ORDER BY filename"
        ).fetchall()
    return [_row_to_stat(r) for r in rows]


def get_stat(filename: str, db_path: Path = _DEFAULT_DB_PATH) -> DanceStat | None:
    """Return the stat for a single filename, or None if not found."""
    with _connect(db_path) as con:
        row = con.execute(
            "SELECT * FROM dance_stats WHERE filename = ?", (filename,)
        ).fetchone()
    return _row_to_stat(row) if row else None


def bootstrap_score(
    filename: str,
    score: float,
    db_path: Path = _DEFAULT_DB_PATH,
) -> DanceStat:
    """
    Set a known-good starting score for *filename* without counting it as a
    real play session.  Only updates rows where play_count = 0 (i.e. never
    actually watched through the app).  Creates the row first if missing.

    Use this once to seed the database for dances you already know well.
    Rows that already have real play history (play_count > 0) are left alone.
    """
    get_or_create(filename, db_path)          # ensure row exists
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    with _connect(db_path) as con:
        con.execute(
            """
            UPDATE dance_stats
               SET historical_score = ?,
                   play_count       = 1,
                   last_played      = ?
             WHERE filename = ?
               AND play_count = 0
            """,
            (round(float(score), 4), now_iso, filename),
        )
        row = con.execute(
            "SELECT * FROM dance_stats WHERE filename = ?", (filename,)
        ).fetchone()
    return _row_to_stat(row)
