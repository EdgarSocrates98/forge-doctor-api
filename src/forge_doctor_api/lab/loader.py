"""Lab scenario discovery + `expected.yaml` parsing.

`labs/<domain>/<scenario>/` — every directory holding an
`expected.yaml` is a scenario; `labs/` itself and `expected.yaml` are
excluded from the fixture surface seen by analyzers.
"""

from __future__ import annotations

import json

import yaml

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.lab.model import LabExpectation, LabScenario

_EXPECTED_NAMES = ("expected.yaml", "expected.yml", "expectations.json")
# Domains whose scenarios must declare where their fixture material came
# from. `oss` is stricter: provenance is only real with a pinned upstream
# ref, a license tag, and the vendored bytes' sha256.
_PROVENANCE_KEYS = {
    "realworld": ("source", "retrieved"),
    "oss": ("source", "upstream_ref", "license", "sha256"),
}


def _list(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    return tuple(str(x) for x in raw) if isinstance(raw, list) else ()


def _expectation(raw: object) -> LabExpectation:
    doc = raw if isinstance(raw, dict) else {}
    return LabExpectation(
        findings=_list(doc.get("expected_findings")),
        forbidden_findings=_list(doc.get("forbidden_findings")),
        description_contains=_list(doc.get("expected_description_contains")),
        forbidden_description_contains=_list(
            doc.get("forbidden_description_contains")
        ),
        entities=_list(doc.get("expected_entities")),
        edges=_list(doc.get("expected_edges")),
        forbidden_entities=_list(doc.get("forbidden_entities")),
        forbidden_edges=_list(doc.get("forbidden_edges")),
        clients=_list(doc.get("expected_clients")),
        breaking=_list(doc.get("expected_breaking")),
        runtime_signals=_list(doc.get("expected_runtime_signals")),
        issues=_list(doc.get("expected_issues")),
    )


def _scenario(context: ProjectContext, rel: str) -> LabScenario:
    path = rel.rsplit("/", 1)[0] if "/" in rel else "."
    domain, _, name = path.partition("/")
    doc: object = None
    try:
        text = context.read_text(rel)
        doc = (json.loads(text) if rel.endswith(".json")
               else yaml.safe_load(text))
    except (OSError, UnicodeDecodeError, yaml.YAMLError,
            json.JSONDecodeError):
        doc = None
    problems: list[str] = []
    if not isinstance(doc, dict):
        problems.append("unparseable expectations file")
        return LabScenario(
            domain=domain or "labs", name=name or path, path=path,
            problems=tuple(problems))
    provenance: tuple[tuple[str, str], ...] = ()
    required = _PROVENANCE_KEYS.get(domain)
    if required is not None:
        prov = doc.get("provenance")
        if not isinstance(prov, dict) or any(k not in prov for k in required):
            problems.append(
                f"{domain} scenario missing provenance block "
                f"(requires {required})")
        else:
            provenance = tuple(sorted(
                (str(k), str(v)) for k, v in prov.items()))
    diff = doc.get("diff")
    diff_old = diff_new = None
    if isinstance(diff, dict):
        diff_old = str(diff.get("old", "before"))
        diff_new = str(diff.get("new", "after"))
    return LabScenario(
        domain=domain or "labs",
        name=name or path,
        path=path,
        run=_list(doc.get("run")),
        diff_old=diff_old,
        diff_new=diff_new,
        hops=_list(doc.get("hops")),
        today=str(doc["today"]) if doc.get("today") else None,
        requires_extras=_list(doc.get("requires_extras")),
        requires_domains=_list(doc.get("requires_domains")),
        expected=_expectation(doc),
        provenance=provenance,
        problems=tuple(problems),
    )


def discover_scenarios(context: ProjectContext) -> tuple[LabScenario, ...]:
    """Find every `expected.yaml` under the root — sorted, deterministic."""
    out: list[LabScenario] = []
    for rel in context.iter_files():
        name = rel.rsplit("/", 1)[-1]
        if name in _EXPECTED_NAMES:
            out.append(_scenario(context, rel))
    return tuple(sorted(out, key=lambda s: (s.domain, s.name)))
