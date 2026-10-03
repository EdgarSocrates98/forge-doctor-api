"""Lab scenario discovery + `expected.yaml` parsing.

`labs/<domain>/<scenario>/` — every directory holding an
`expected.yaml` is a scenario; `labs/` itself and `expected.yaml` are
excluded from the fixture surface seen by analyzers.
"""

from __future__ import annotations

import yaml

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.lab.model import LabExpectation, LabScenario

_EXPECTED_NAMES = ("expected.yaml", "expected.yml")


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
        doc = yaml.safe_load(context.read_text(rel))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        doc = None
    if not isinstance(doc, dict):
        return LabScenario(
            domain=domain or "labs", name=name or path, path=path,
        )
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
        expected=_expectation(doc),
    )


def discover_scenarios(context: ProjectContext) -> tuple[LabScenario, ...]:
    """Find every `expected.yaml` under the root — sorted, deterministic."""
    out: list[LabScenario] = []
    for rel in context.iter_files():
        name = rel.rsplit("/", 1)[-1]
        if name in _EXPECTED_NAMES:
            out.append(_scenario(context, rel))
    return tuple(sorted(out, key=lambda s: (s.domain, s.name)))
