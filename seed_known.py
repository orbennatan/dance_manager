"""
seed_known.py  –  Bootstrap all dances as "well known"
=======================================================
Run this ONCE when you already know all the dances and just want the system
to start tracking from a high baseline instead of treating everything as new.

What it does
------------
For every video file in VIDEO_FOLDER:
  • If the file has never been watched in the app (play_count == 0):
      → sets historical_score = BOOT_SCORE  (default 85.0 → Pool C Mastered)
      → sets play_count = 1  (so the badge shows a score, not "New")
  • If the file already has real play history (play_count > 0):
      → left completely untouched  (real data is never overwritten)

Forgetting is handled automatically
-------------------------------------
The EMA formula keeps the system honest.  Starting at 85.0:

  One bad session (score 30, lots of rewinds):
    new = 0.30 × 30  +  0.70 × 85  =  68.5  → demoted to Pool B

  Two bad sessions in a row:
    new = 0.30 × 30  +  0.70 × 68.5 = 57.0  → demoted back to Pool A

So if you genuinely forget a dance the system will catch it within 1-2 sessions
and put it back into your daily learning rotation automatically.

Usage
-----
    python seed_known.py              # uses default BOOT_SCORE = 85.0
    python seed_known.py --score 90   # start even higher
    python seed_known.py --dry-run    # preview without writing anything
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Force UTF-8 output so Hebrew filenames don't crash on Windows cp1252 consoles
if sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import db
import recommender

VIDEO_FOLDER = Path(r"C:\Users\orben\OneDrive\DanceManager\Dances\9")
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"}
DEFAULT_BOOT_SCORE = 85.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed known dances into the database.")
    parser.add_argument(
        "--score", type=float, default=DEFAULT_BOOT_SCORE,
        help=f"Starting historical score (default {DEFAULT_BOOT_SCORE}). "
             "85+ = Pool C Mastered, 60-84 = Pool B Familiar.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen without writing to the database.",
    )
    args = parser.parse_args()

    boot_score: float = max(0.0, min(100.0, args.score))
    dry_run: bool = args.dry_run

    if not VIDEO_FOLDER.exists():
        print(f"ERROR: folder not found: {VIDEO_FOLDER}")
        return

    files = sorted(
        f for f in VIDEO_FOLDER.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    )

    db.init_db()
    pool_label = recommender.pool_label(boot_score).replace("\u2013", "-")

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Seeding {len(files)} dances")
    print(f"  Starting score : {boot_score:.1f}  ({pool_label})")
    print(f"  Folder         : {VIDEO_FOLDER}")
    print()

    seeded = 0
    skipped = 0
    already_tracked = 0

    for f in files:
        stat = db.get_stat(f.name)

        if stat is not None and stat.play_count > 0:
            # Real play history exists – do not touch it
            already_tracked += 1
            print(f"  SKIP (tracked)  {f.name}  [score={stat.historical_score:.1f}  plays={stat.play_count}]")
            continue

        if dry_run:
            action = "NEW→seed" if stat is None else "zero→seed"
            print(f"  {action:12s}  {f.name}  => score={boot_score:.1f}")
            seeded += 1
        else:
            result = db.bootstrap_score(f.name, boot_score)
            action = "Seeded (new)" if stat is None else "Seeded (was 0)"
            print(f"  {action:14s}  {f.name}  => score={result.historical_score:.1f}")
            seeded += 1

    print()
    print(f"{'[DRY RUN] ' if dry_run else ''}Done.")
    print(f"  Seeded          : {seeded}")
    print(f"  Already tracked : {already_tracked}  (untouched)")
    print()

    if not dry_run:
        # Final pool breakdown
        all_stats = db.get_all()
        avail = {f.name for f in files}
        pool_a, pool_b, pool_c = recommender.split_into_pools(all_stats, avail)
        print(f"Pool breakdown after seed:")
        print(f"  A - Learning  (0-59)  : {len(pool_a)}")
        print(f"  B - Familiar  (60-84) : {len(pool_b)}")
        print(f"  C - Mastered  (85+)   : {len(pool_c)}")
        print()


if __name__ == "__main__":
    main()
