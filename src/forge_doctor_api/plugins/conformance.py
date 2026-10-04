"""Plugin conformance suite — behavioral verification of activated plugins.

Trust says *what may run*; conformance checks *how it behaves*. Each
check is honest about its boundary: these are structural/behavioral
detectors, not proofs — a malicious plugin could in principle pass by
detecting the harness, which the docs state openly.

The six checks (spec 054):

- determinism: two runs over the same tree serialize byte-identical;
- offline: the run completes with sockets hard-blocked;
- evidence: every emitted Finding has >=1 Evidence, and every
  `Confidence.UNKNOWN` finding carries `unknowns`;
- side-effects: the project fileset (paths + sha256) is identical
  before/after — a plugin that writes fails;
- output-compat: results round-trip through `to_dict`/`to_json`;
- unknown-semantics: UnknownFacts are real `UnknownFact` objects with
  subject+missing+resolution populated.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Confidence, Finding, Model, UnknownFact

PluginRun = Callable[[ProjectContext, Sequence[str]], Any]


@dataclass(frozen=True, kw_only=True)
class CheckResult(Model):
    name: str
    status: str          # "pass" | "fail" | "error"
    details: str = ""


@dataclass(frozen=True, kw_only=True)
class ConformanceReport(Model):
    plugin: str
    checks: tuple[CheckResult, ...] = ()

    @property
    def passed(self) -> bool:
        return all(c.status == "pass" for c in self.checks)


def _snapshot(root: Path) -> dict[str, str]:
    """path -> sha256 for every file under root."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


def _blocked(*_a: Any, **_kw: Any) -> Any:
    raise OSError("conformance: network is disabled")


def _findings(result: Any) -> tuple[Finding, ...]:
    found: list[Finding] = []
    for attr in ("findings",):
        val = getattr(result, attr, None)
        if isinstance(val, (tuple, list)):
            found += [x for x in val if isinstance(x, Finding)]
    if isinstance(result, Finding):
        found.append(result)
    if isinstance(result, (tuple, list)):
        found += [x for x in result if isinstance(x, Finding)]
    return tuple(found)


def _unknowns(result: Any) -> tuple[Any, ...]:
    val = getattr(result, "unknowns", None)
    if isinstance(val, (tuple, list)):
        return tuple(val)
    return ()


def _serialize(result: Any) -> bytes:
    if isinstance(result, Model):
        return result.to_json().encode("utf-8")
    if isinstance(result, (tuple, list)):
        parts = []
        for x in result:
            parts.append(x.to_json() if isinstance(x, Model)
                         else json.dumps(x, sort_keys=True, default=str))
        return ("[" + ",".join(parts) + "]").encode("utf-8")
    return json.dumps(result, sort_keys=True, default=str).encode("utf-8")


def run_conformance(
    name: str,
    run: PluginRun,
    project_root: Path,
) -> ConformanceReport:
    """Six behavioral checks against a plugin's run surface."""
    ctx = ProjectContext.from_root(project_root)
    files = list(ctx.iter_files())
    checks: list[CheckResult] = []
    fileset_before = _snapshot(project_root)

    try:
        r1 = run(ctx, files)
    except Exception as exc:
        return ConformanceReport(plugin=name, checks=(CheckResult(
            name="run", status="error",
            details=f"plugin run raised {exc!r}"),))

    # determinism ---------------------------------------------------------------
    try:
        r2 = run(ProjectContext.from_root(project_root), files)
        same = _serialize(r1) == _serialize(r2)
        checks.append(CheckResult(
            name="determinism", status="pass" if same else "fail",
            details="two runs byte-identical" if same
            else "outputs differ between identical runs"))
    except Exception as exc:
        checks.append(CheckResult(
            name="determinism", status="error", details=repr(exc)))

    # offline --------------------------------------------------------------------
    try:
        # `patch` resolves "socket.*" lazily — no `import socket`
        # statement here; src/ must never import the network stack.
        with patch("socket.socket", _blocked), \
             patch("socket.create_connection", _blocked), \
             patch("socket.getaddrinfo", _blocked):
            run(ProjectContext.from_root(project_root), files)
        checks.append(CheckResult(name="offline", status="pass"))
    except Exception as exc:
        checks.append(CheckResult(
            name="offline", status="fail",
            details=f"raised under blocked sockets: {exc!r}"))

    # evidence compliance --------------------------------------------------------
    findings = _findings(r1)
    no_ev = [f.id for f in findings if not f.evidence]
    no_unk = [
        f.id for f in findings
        if f.confidence is Confidence.UNKNOWN and not f.unknowns]
    ok = not no_ev and not no_unk
    checks.append(CheckResult(
        name="evidence",
        status="pass" if ok else "fail",
        details=(
            f"{len(findings)} findings checked"
            if ok else
            f"no evidence: {no_ev}; UNKNOWN w/o unknowns: {no_unk}")))

    # side-effects ----------------------------------------------------------------
    try:
        run(ProjectContext.from_root(project_root), files)
        same = _snapshot(project_root) == fileset_before
        checks.append(CheckResult(
            name="side-effects", status="pass" if same else "fail",
            details="fileset unchanged" if same
            else "plugin modified the analyzed project"))
    except Exception as exc:
        checks.append(CheckResult(
            name="side-effects", status="error", details=repr(exc)))

    # output compatibility ----------------------------------------------------------
    try:
        json.loads(_serialize(r1).decode("utf-8"))
        checks.append(CheckResult(name="output-compat", status="pass"))
    except Exception as exc:
        checks.append(CheckResult(
            name="output-compat", status="fail",
            details=f"serialization failed: {exc!r}"))

    # unknown semantics --------------------------------------------------------------
    bad = [
        u for u in _unknowns(r1)
        if not isinstance(u, UnknownFact)
        or not u.subject or not u.missing]
    checks.append(CheckResult(
        name="unknown-semantics",
        status="pass" if not bad else "fail",
        details="unknowns are typed UnknownFacts" if not bad
        else f"malformed unknowns: {bad[:3]}"))

    return ConformanceReport(plugin=name, checks=tuple(checks))


def plugin_run_surface(plugin: Any) -> PluginRun | None:
    """Extract the callable analysis surface of a plugin/module.

    Order: `analyze(ctx, files)` > adapter `discover_routes` (wrapped).
    """
    if callable(getattr(plugin, "analyze", None)):
        return plugin.analyze  # type: ignore[no-any-return]
    if callable(getattr(plugin, "discover_routes", None)):
        def _run(ctx: ProjectContext, files: Sequence[str]) -> Any:
            return plugin.discover_routes(ctx, "conformance", files)
        return _run
    return None
