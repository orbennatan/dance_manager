"""
Spaced-repetition progression simulator
========================================
Shows how a dance moves through the pools over N days given a fixed
session score per day.  Run directly:

    python simulate.py

No VLC or real video files needed.
"""
from __future__ import annotations

from scorer import EMA_ALPHA
from recommender import pool_label

POOL_A_THRESHOLD = 60.0
POOL_B_THRESHOLD = 85.0


def simulate(
    days: int = 10,
    session_score: float = 100.0,
    start_score: float = 0.0,
    label: str = "",
) -> None:
    score = start_score
    header = f"  {'Day':>3}  {'Session':>7}  {'New score':>9}  Pool"
    tag = f"── {label or f'session_score={session_score:.0f}'} ──"
    print(f"\n{tag}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for day in range(1, days + 1):
        new_score = (EMA_ALPHA * session_score) + ((1 - EMA_ALPHA) * score)
        pool = pool_label(new_score)
        promoted = ""
        if score < POOL_A_THRESHOLD <= new_score:
            promoted = "  ← PROMOTED to Pool B!"
        elif score < POOL_B_THRESHOLD <= new_score:
            promoted = "  ← PROMOTED to Pool C!"
        print(f"  {day:>3}  {session_score:>7.1f}  {new_score:>9.1f}  {pool}{promoted}")
        score = new_score
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("  Dance Manager – Spaced Repetition Simulator")
    print("=" * 60)

    simulate(days=10, session_score=100.0, label="Perfect every day")
    simulate(days=10, session_score=80.0,  label="One rewind per session (~80)")
    simulate(days=15, session_score=60.0,  label="Struggling (score ~60)")

    # Show what happens if you stumble on day 4 (after 3 perfect days → score≈65)
    print("── Stumble on Day 4 (big rewind → session=30 after 3 perfect days) ──")
    header = f"  {'Day':>3}  {'Session':>7}  {'New score':>9}  Pool"
    print(header)
    print("  " + "-" * (len(header) - 2))
    score = 0.0
    sessions = [100, 100, 100, 30, 100, 100, 100, 100, 100, 100]
    for day, ss in enumerate(sessions, 1):
        new_score = (EMA_ALPHA * ss) + ((1 - EMA_ALPHA) * score)
        pool = pool_label(new_score)
        flag = ""
        if score < POOL_A_THRESHOLD <= new_score:
            flag = "  ← PROMOTED to Pool B!"
        elif score < POOL_B_THRESHOLD <= new_score:
            flag = "  ← PROMOTED to Pool C!"
        print(f"  {day:>3}  {ss:>7.1f}  {new_score:>9.1f}  {pool}{flag}")
        score = new_score
    print()
