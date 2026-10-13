"""§179-180 backward-compatibility baseline - fingerprint-keyed store.

A baseline anchors semantic diffs without VCS access: record the semantic
fingerprint of the contract a deployment was built against; later diffs
anchor to that fingerprint rather than to a git revision.
"""

from __future__ import annotations

import json
from typing import Any

from forge_doctor_api.analyzers.openapi import OpenApiProjectModel
from forge_doctor_api.change.model import BackwardCompatibilityBaseline, BaselineEntry
from forge_doctor_api.checks.compat import semantic_fingerprint


def record_baseline(
    baseline: BackwardCompatibilityBaseline,
    model: OpenApiProjectModel,
    *,
    label: str,
    recorded_at: str,
) -> BackwardCompatibilityBaseline:
    """Store the semantic fingerprint of `model` under `label`.

    `recorded_at` is supplied by the caller (no wall-clock reads inside the
    engine keep diff/baseline behavior deterministic).
    """
    return baseline.record(
        BaselineEntry(
            fingerprint=semantic_fingerprint(model),
            label=label,
            recorded_at=recorded_at,
            subject_count=len(model.operations),
        )
    )


def baseline_to_json(baseline: BackwardCompatibilityBaseline) -> str:
    """Serialize the baseline store — compact entries only, no payloads."""
    return json.dumps(baseline.to_dict(), sort_keys=True, indent=2)


def baseline_from_json(text: str) -> BackwardCompatibilityBaseline:
    """Parse a baseline store produced by `baseline_to_json`."""
    data: Any = json.loads(text)
    if not isinstance(data, dict) or "entries" not in data:
        msg = "not a baseline store: expected an object with an `entries` list"
        raise ValueError(msg)
    return BackwardCompatibilityBaseline.from_dict(data)
