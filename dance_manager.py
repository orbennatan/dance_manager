#!/usr/bin/env python3
"""
dance_manager – a spaced-repetition video player for learning dances.

Usage
-----
    python dance_manager.py

Optional arguments
------------------
--data-file PATH    Path to the JSON session-data file
                    (default: ~/.dance_manager_data.json)
"""

import argparse
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Dance Manager – spaced-repetition video player"
    )
    parser.add_argument(
        "--data-file",
        default=None,
        help="Path to the session-data JSON file (default: ~/.dance_manager_data.json)",
    )
    args = parser.parse_args(argv)

    # Import here so that the module is only loaded when actually running the GUI
    from player.app import run, _DEFAULT_DATA_FILE

    data_file = args.data_file or _DEFAULT_DATA_FILE
    run(data_file=data_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
