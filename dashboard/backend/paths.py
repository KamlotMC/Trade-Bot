"""Shared path helpers for dashboard runtime files."""
from pathlib import Path
from typing import Iterable


def _candidate_roots() -> Iterable[Path]:
    repo_root = Path(__file__).resolve().parents[2]
    yield Path.cwd()
    yield repo_root
    yield Path.home() / "Trade-Bot"


def find_project_file(*parts: str) -> Path:
    """Return the first existing file path from known project roots.

    Falls back to the repository-root-based location when nothing exists yet,
    so callers can still create files in a deterministic place.
    """
    rel = Path(*parts)
    for root in _candidate_roots():
        candidate = root / rel
        if candidate.exists():
            return candidate

    return Path(__file__).resolve().parents[2] / rel

