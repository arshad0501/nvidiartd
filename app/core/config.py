"""Bounded configuration shared by CLI, API and tests."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("DRIVESENSE_DATA_DIR", PROJECT_ROOT / "data")).resolve()
MAX_CSV_BYTES = 10 * 1024 * 1024
MAX_REVIEWS = 20_000
MAX_TEXT_LENGTH = 12_000
PIPELINE_VERSION = "2.0.0"


class InputError(ValueError):
    """A safe, actionable error that can be returned to a client."""


class BusyError(RuntimeError):
    pass


def resolve_csv(value=None):
    """Only allow real CSV files within the configured dataset directory."""
    root = DATA_DIR.resolve()
    path = Path(value) if value else root / "reviews_raw.csv"
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_relative_to(root):
        raise InputError("Choose a CSV inside the configured data directory.")
    if path.suffix.lower() != ".csv" or not path.is_file():
        raise InputError("Dataset CSV was not found in the data directory.")
    if path.stat().st_size > MAX_CSV_BYTES:
        raise InputError("CSV exceeds the 10 MiB input limit.")
    return path
