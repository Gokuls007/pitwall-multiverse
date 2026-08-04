"""FastF1 cache configuration.

This module — and the rest of `ingestion/` — is the *only* place FastF1 is
imported anywhere in the codebase (see CLAUDE.md, spec 2.2/2.3). Everything
inward of the ingestion boundary deals only in domain objects.
"""

from __future__ import annotations

from pathlib import Path

import fastf1

# Repo root is four levels up from this file: ingestion/ -> pitwall/ -> backend/ -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIR = _REPO_ROOT / "data" / "cache"

_enabled = False


def enable_cache(cache_dir: Path | str | None = None) -> Path:
    """Enable the FastF1 cache, creating the directory if needed.

    Idempotent — safe to call multiple times (e.g. once per script entry point).
    """
    global _enabled
    path = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(path))
    _enabled = True
    return path
