"""OWASP API Top 10 knowledge-pack loader (§49, §128, §129).

The pack is a bundled YAML data file - categories update without code
changes; the file is read once per process via `importlib.resources`
(hermetic, package-internal, no host filesystem access).
"""

from __future__ import annotations

from importlib import resources
from typing import Any

import yaml

from forge_doctor_api.core.models import ModelError

_PACK = "forge_doctor_api.knowledge.security"
_FILE = "owasp_api_top10.yaml"


def _doc() -> dict[str, Any]:
    text = (
        resources.files(_PACK).joinpath(_FILE).read_text(encoding="utf-8")
    )
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict) or "categories" not in doc:
        raise ModelError(f"malformed security knowledge pack: {_FILE}")
    return doc


def owasp_categories() -> dict[str, str]:
    """`API1` .. `API10` -> category name."""
    return {
        str(k): str(v["name"])
        for k, v in _doc()["categories"].items()
    }


def check_to_owasp(check_id: str) -> tuple[str, ...]:
    """OWASP category codes mapped to a check id (possibly several)."""
    out = []
    for code, entry in _doc()["categories"].items():
        if check_id in (entry.get("checks") or []):
            out.append(str(code))
    return tuple(sorted(set(out)))
