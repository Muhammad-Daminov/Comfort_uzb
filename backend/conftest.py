"""Ensures `app` (backend/app) is importable as a top-level package when
pytest is run from the `backend/` directory, without requiring an editable
install."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
