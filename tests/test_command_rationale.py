"""Every documented command must resolve to curated rationale.

Coverage contract (docs/reference/command-rationale.json):
- every command in commands.generated.json resolves via longest-prefix
  match (a leaf override wins over its first-level group entry);
- the resolved entry carries non-empty ``why`` and ``when`` fields
  (``when_not`` is optional — only where the distinction is real);
- every rationale key is a real command path or a real path prefix —
  a typo'd key fails loudly instead of silently covering nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / "docs" / "reference" / "commands.generated.json"
RAT = ROOT / "docs" / "reference" / "command-rationale.json"


def _resolve(rationale: dict, path: str) -> tuple[str, dict] | None:
    words = path.split()
    for n in range(len(words), 0, -1):
        key = " ".join(words[:n])
        if key in rationale:
            return key, rationale[key]
    return None


@pytest.fixture(scope="module")
def inventory() -> dict:
    assert INV.exists(), f"missing {INV} — run scripts/docs/regen_docs.py"
    return json.loads(INV.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rationale() -> dict:
    assert RAT.exists(), f"missing {RAT}"
    return json.loads(RAT.read_text(encoding="utf-8"))


def test_every_command_resolves_rationale(inventory, rationale):
    missing = [
        c["path"] for c in inventory["commands"]
        if _resolve(rationale, c["path"]) is None
    ]
    assert not missing, f"commands without rationale: {missing[:20]}"


def test_resolved_rationale_has_required_fields(inventory, rationale):
    bad = []
    for c in inventory["commands"]:
        hit = _resolve(rationale, c["path"])
        assert hit is not None, c["path"]
        key, entry = hit
        for field in ("why", "when"):
            if not (entry.get(field) or "").strip():
                bad.append(f"{c['path']} (via `{key}`): empty `{field}`")
    assert not bad, "\n".join(bad[:20])


def test_rationale_keys_are_real_paths(inventory, rationale):
    paths = {c["path"] for c in inventory["commands"]}
    prefixes = {
        " ".join(p.split()[:n])
        for p in paths
        for n in range(1, len(p.split()) + 1)
    }
    bogus = [k for k in rationale if k not in prefixes]
    assert not bogus, f"rationale keys matching no command: {bogus}"


def test_rationale_entries_have_known_shape(rationale):
    allowed = {"why", "when", "when_not"}
    bad = [
        f"{k}: unknown fields {sorted(set(v) - allowed)}"
        for k, v in rationale.items()
        if set(v) - allowed
    ]
    assert not bad, "\n".join(bad)
