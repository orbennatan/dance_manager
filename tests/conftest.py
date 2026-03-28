"""Make the project root importable from the tests/ subdirectory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
