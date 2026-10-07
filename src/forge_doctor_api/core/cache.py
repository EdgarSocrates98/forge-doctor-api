"""Spec 065 — incremental engine: file-backed per-analyzer cache.

Opt-in only: `AnalysisCache` is instantiated exclusively when the
caller passes ``incremental=True`` / ``--incremental``. The default
path is a full deterministic scan — identical bytes, no cache dir.

Keys bind a cache entry to everything that could change its value:

- the analyzer id,
- the tool version,
- a caller-supplied config digest (e.g. ``keep_spans`` for runtime),
- the sorted sha256 set of the artifacts the analyzer consumed
  (from the `EvidenceStore` — content, not mtime).

Touching one artifact changes only the shas of the analyzers that
consumed it — every other analyzer key stays warm. A miss, a corrupt
entry, or a model that fails `from_dict` all fall back to full
analysis: the cache is an accelerator, never a source of truth.

Values are analyzer-level compact model dicts only — `to_dict()` of
the model a loader returns. Check findings, report-level unknowns and
cross-artifact results are never stored: checks always recompute over
the (possibly cached) models, so a stale key can never resurrect a
suppressed finding. A model's own `unknowns` field (the analyzer's
diagnostic output, part of its compact model) round-trips with the
model — it is recomputed indirectly since only identical input bytes
can produce a key hit.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

CACHE_DIR_NAME = ".forge-doctor"


class AnalysisCache:
    """File-backed analyzer cache rooted at ``<project>/.forge-doctor/cache``."""

    def __init__(self, project_root: Any, *, tool_version: str) -> None:
        from pathlib import Path

        self._dir = Path(project_root) / CACHE_DIR_NAME / "cache"
        self._tool_version = tool_version
        self.hits = 0
        self.misses = 0

    @property
    def directory(self) -> Any:
        return self._dir

    def key(
        self,
        analyzer: str,
        input_shas: Iterable[str],
        config_digest: str,
    ) -> str:
        """Content key: analyzer | tool version | config | artifact shas."""
        material = json.dumps(
            [analyzer, self._tool_version, config_digest,
             sorted(input_shas)],
            separators=(",", ":"))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    def get(
        self,
        analyzer: str,
        input_shas: Iterable[str],
        config_digest: str,
    ) -> dict[str, Any] | None:
        """Cached analyzer model dict, or None on miss/corruption."""
        key = self.key(analyzer, input_shas, config_digest)
        try:
            payload = json.loads(
                (self._dir / f"{key}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.misses += 1
            return None
        if (not isinstance(payload, dict)
                or payload.get("key") != key
                or payload.get("analyzer") != analyzer
                or payload.get("tool_version") != self._tool_version
                or not isinstance(payload.get("model"), dict)):
            self.misses += 1
            return None
        self.hits += 1
        model: dict[str, Any] = payload["model"]
        return model

    def put(
        self,
        analyzer: str,
        input_shas: Iterable[str],
        config_digest: str,
        model: dict[str, Any],
    ) -> None:
        """Persist one analyzer-level model dict (best effort)."""
        key = self.key(analyzer, input_shas, config_digest)
        payload = {
            "key": key,
            "analyzer": analyzer,
            "tool_version": self._tool_version,
            "model": model,
        }
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            (self._dir / f"{key}.json").write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False),
                encoding="utf-8")
        except OSError:
            return  # cache is best-effort; never fail a scan over it
