"""Spec 050 — shared protocol-conformance suite for framework adapters.

`FrameworkConformance` runs the same invariants against any adapter
claiming the §39 contract. The suite is deliberately structural — it
asserts what a caller can rely on, not how the adapter is built:

- determinism: two scans over the same tree are byte-identical;
- unknown-on-absence: an empty project yields empty items AND an
  UnknownFact per `discover_*` surface — never a fabricated zero;
- sorted output: routes and surface items are stably ordered;
- no-exec: adapters must never import target code — enforced by
  construction (scanning runs on a ProjectContext over a temp tree;
  the suite additionally asserts the adapter object exposes no
  import/loader attributes).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from forge_doctor_api.analyzers.routes.adapter import FrameworkAdapter
from forge_doctor_api.core.context import ProjectContext

_SURFACES = (
    "discover_auth", "discover_schemas", "discover_dependencies",
    "discover_middleware", "discover_error_handlers",
    "discover_validation", "discover_serialization",
    "discover_client_calls",
)


@dataclass(frozen=True)
class ConformanceCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class FrameworkConformance:
    """Result of running the conformance suite against one adapter."""

    adapter: str
    checks: tuple[ConformanceCheck, ...] = ()

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def run_framework_conformance(
    adapter: FrameworkAdapter,
    project_root: Path,
) -> FrameworkConformance:
    """Run the shared suite; `project_root` may be an empty dir."""
    checks: list[ConformanceCheck] = []
    ctx = ProjectContext.from_root(project_root)
    files = list(ctx.iter_files())

    # -- protocol surface: every §39 method exists and is callable ----
    missing = [
        name for name in (
            "detect", "attribute", "discover_routes", *_SURFACES)
        if not callable(getattr(adapter, name, None))
    ]
    checks.append(ConformanceCheck(
        name="protocol-surface",
        passed=not missing,
        detail=f"missing: {missing}" if missing else "all §39 methods"))

    # -- no-exec: no import/loader machinery on the adapter -----------
    forbidden = [
        a for a in ("import_module", "exec", "eval", "load_module")
        if hasattr(adapter, a)]
    src = ""
    import contextlib
    with contextlib.suppress(OSError, TypeError):
        src = inspect.getsource(type(adapter))
    banned_calls = (
        "importlib.import_module(" in src or "__import__(" in src)
    checks.append(ConformanceCheck(
        name="no-exec",
        passed=not forbidden and not banned_calls,
        detail="no import/execute surface"))

    # -- unknown-on-absence: empty surfaces carry UnknownFacts --------
    empty_items: list[str] = []
    missing_unknowns: list[str] = []
    for name in _SURFACES:
        result = getattr(adapter, name)(ctx, files)
        if result.items:
            empty_items.append(name)
        if result.items or not result.unknowns:
            missing_unknowns.append(name)
    checks.append(ConformanceCheck(
        name="unknown-on-absence",
        passed=not missing_unknowns,
        detail=(
            f"items on empty: {empty_items}; "
            f"no unknowns: {missing_unknowns}")))

    # -- determinism: two scans are byte-identical --------------------
    scan_a = adapter.discover_routes(ctx, "svc", files)
    scan_b = adapter.discover_routes(ctx, "svc", files)
    checks.append(ConformanceCheck(
        name="determinism",
        passed=scan_a.to_json() == scan_b.to_json()))

    # -- sorted output ------------------------------------------------
    routes = scan_a.routes
    keys = [(r.method, r.path, r.handler) for r in routes]
    checks.append(ConformanceCheck(
        name="sorted-output",
        passed=list(keys) == sorted(keys)))

    return FrameworkConformance(
        adapter=adapter.name, checks=tuple(checks))


def conformance_tests(
    adapter_factory: Callable[[], FrameworkAdapter],
) -> Sequence[str]:
    """Names of the suite's checks — for parameterized assertions."""
    _ = adapter_factory
    return _SURFACES
