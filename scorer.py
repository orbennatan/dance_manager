"""
Dance Manager – Session Scorer
================================
Tracks user behaviour during a single video playback session and computes
a 0–100 session score that feeds the Exponential Moving Average (EMA) model.

Scoring Model
-------------
A perfect run (no rewinds) → session_score = 100.

Each **backward seek** (rewind) subtracts a penalty proportional to how far
back the user scrubbed relative to the total video length.  Short, accidental
nudges near the start of the video count less than long scrubs mid-dance.

  per_rewind_penalty = (rewind_distance_ms / video_length_ms) * MAX_PENALTY_PER_REWIND

Total penalty is capped at 100 so the score never goes negative.

After the session the historical EMA is updated:

  new_historical = (EMA_ALPHA * session_score) + ((1 - EMA_ALPHA) * old_historical)

Constants (all tunable)
-----------------------
EMA_ALPHA              = 0.30  – weight given to the most recent session
MAX_PENALTY_PER_REWIND = 20    – maximum points lost for a single rewind
                                 (a 100 % scrub-back costs at most 20 pts)

Usage
-----
    scorer = SessionScorer(filename="samba.mp4")
    scorer.start(video_length_ms=180_000, old_historical_score=30.0)

    # … user plays video …
    scorer.register_rewind(from_ms=90_000, to_ms=30_000)  # scrubbed back 60 s

    result = scorer.finalize()
    # result.session_score    – 0-100
    # result.new_historical   – EMA-updated score
    # result.rewind_count     – total backward seeks

    # Persist:
    import db
    db.update_score(scorer.filename, result.new_historical)
"""

from __future__ import annotations

from dataclasses import dataclass, field

EMA_ALPHA: float = 0.30
MAX_PENALTY_PER_REWIND: float = 20.0


@dataclass
class ScoreResult:
    """Outcome of a single viewing session."""

    filename: str
    session_score: float          # 0–100, computed for this viewing
    old_historical: float         # score before this session
    new_historical: float         # EMA-blended score after this session
    rewind_count: int             # number of backward seeks recorded
    total_penalty: float          # total points deducted


@dataclass
class SessionScorer:
    """
    Stateful scorer for one video being watched right now.

    Call `start()` when the video begins playing (or whenever you know the
    length and old score), then `register_rewind()` on every backward seek,
    then `finalize()` when the video ends or the user moves on.
    """

    filename: str
    _video_length_ms: int = field(default=0, init=False, repr=False)
    _old_historical: float = field(default=0.0, init=False, repr=False)
    _rewind_penalties: list[float] = field(default_factory=list, init=False, repr=False)
    _started: bool = field(default=False, init=False, repr=False)

    def start(self, video_length_ms: int, old_historical_score: float) -> None:
        """
        (Re)initialise the scorer for a new viewing of this file.

        Parameters
        ----------
        video_length_ms:
            Total duration of the video.  Pass 0 if unknown; rewind penalty
            will then fall back to a flat MAX_PENALTY_PER_REWIND per rewind.
        old_historical_score:
            The current value from the database (used in the EMA calculation).
        """
        self._video_length_ms = max(0, video_length_ms)
        self._old_historical = float(old_historical_score)
        self._rewind_penalties = []
        self._started = True

    def register_rewind(self, from_ms: int, to_ms: int) -> None:
        """
        Record a backward seek event.

        Parameters
        ----------
        from_ms:
            Position (ms) the user was at before the seek.
        to_ms:
            Position (ms) the user seeked TO.

        Only counted if `to_ms < from_ms` (i.e. it's genuinely backward).
        Silently ignored if the scorer hasn't been started yet.
        """
        if not self._started:
            return

        distance_ms = from_ms - to_ms
        if distance_ms <= 0:
            return  # not a rewind

        if self._video_length_ms > 0:
            fraction = distance_ms / self._video_length_ms
            penalty = min(fraction * MAX_PENALTY_PER_REWIND * 5, MAX_PENALTY_PER_REWIND)
            # The ×5 multiplier means a 20 % scrub-back already costs the full
            # MAX_PENALTY_PER_REWIND, while tiny accidental nudges barely score.
        else:
            # Length unknown – apply a flat penalty
            penalty = MAX_PENALTY_PER_REWIND

        self._rewind_penalties.append(penalty)

    def finalize(self) -> ScoreResult:
        """
        Compute the session score, apply the EMA, and return a `ScoreResult`.

        Can be called even if `start()` was never called (returns a no-op result
        with unchanged historical score).
        """
        if not self._started:
            return ScoreResult(
                filename=self.filename,
                session_score=100.0,
                old_historical=self._old_historical,
                new_historical=self._old_historical,
                rewind_count=0,
                total_penalty=0.0,
            )

        total_penalty = min(sum(self._rewind_penalties), 100.0)
        session_score = max(0.0, 100.0 - total_penalty)

        new_historical = (EMA_ALPHA * session_score) + (
            (1 - EMA_ALPHA) * self._old_historical
        )
        new_historical = round(max(0.0, min(100.0, new_historical)), 4)

        return ScoreResult(
            filename=self.filename,
            session_score=round(session_score, 2),
            old_historical=self._old_historical,
            new_historical=new_historical,
            rewind_count=len(self._rewind_penalties),
            total_penalty=round(total_penalty, 2),
        )

    def reset(self) -> None:
        """Clear accumulated rewind data without changing the filename."""
        self._video_length_ms = 0
        self._old_historical = 0.0
        self._rewind_penalties = []
        self._started = False
