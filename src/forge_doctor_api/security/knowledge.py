"""OWASP API Top 10 knowledge-pack facade (§49, §128, §129).

The pack is a bundled YAML data file — categories update without code
changes; loading goes through the §127-validating pack loader.
"""

from __future__ import annotations

from forge_doctor_api.knowledge.loader import load_pack

_PACK = load_pack("security", "owasp_api_top10.yaml")


def owasp_categories() -> dict[str, str]:
    """`API1` .. `API10` -> category name."""
    return {
        entry.id: str(entry.fields["name"])
        for entry in _PACK.entries
        if "name" in entry.fields
    }


def check_to_owasp(check_id: str) -> tuple[str, ...]:
    """OWASP category codes mapped to a check id (possibly several)."""
    out = []
    for entry in _PACK.entries:
        if check_id in (entry.fields.get("checks") or ()):
            out.append(entry.id)
    return tuple(sorted(set(out)))
