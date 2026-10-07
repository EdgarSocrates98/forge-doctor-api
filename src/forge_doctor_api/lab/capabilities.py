"""Optional-capability detection for the lab harness.

`pip install .` ships the core; `pip install '.[graphql,mcp]'` activates
optional analyzers. Detection never imports the extra — it probes
`importlib.util.find_spec` so a missing capability is an explicit,
recorded state rather than a crash or a vacuous pass.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Iterable
from importlib.machinery import ModuleSpec
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge_doctor_api.lab.model import LabScenario

# Declared optional extras -> the import module that proves them.
EXTRA_MODULES: dict[str, str] = {
    "graphql": "graphql",
    "mcp": "mcp",
}

# Lab pipeline names (`run:` entries) -> the extra they need.
PIPELINE_EXTRAS: dict[str, str] = {
    "graphql": "graphql",
}

# Lab domain directories -> the extra they need.
DOMAIN_EXTRAS: dict[str, str] = {
    "graphql": "graphql",
}

# Bound once so tests can patch the probe without touching importlib.
_find_spec: Callable[[str], ModuleSpec | None] = importlib.util.find_spec


def extra_available(name: str) -> bool:
    """True when the declared extra's module is importable."""
    module = EXTRA_MODULES.get(name)
    if module is None:
        return False  # undeclared extra — never claimed available
    try:
        return _find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def extras_present() -> tuple[str, ...]:
    """Declared extras whose module resolves — sorted."""
    return tuple(sorted(n for n in EXTRA_MODULES if extra_available(n)))


def extras_absent() -> tuple[str, ...]:
    """Declared extras whose module does not resolve — sorted."""
    return tuple(sorted(n for n in EXTRA_MODULES if not extra_available(n)))


def missing_extras(names: Iterable[str]) -> tuple[str, ...]:
    """The subset of `names` not importable — sorted, deduplicated."""
    return tuple(sorted({n for n in names if not extra_available(n)}))


def scenario_requirements(scenario: LabScenario) -> tuple[str, ...]:
    """Extras a scenario needs: declared + implied by domain/run/domain deps."""
    required: set[str] = set(scenario.requires_extras)
    for domain in scenario.requires_domains:
        extra = DOMAIN_EXTRAS.get(domain)
        if extra is not None:
            required.add(extra)
    if scenario.domain in DOMAIN_EXTRAS:
        required.add(DOMAIN_EXTRAS[scenario.domain])
    # An explicit `run:` list is a declared contract — a scenario that
    # says it runs graphql must prove it (default-run scenarios keep
    # minimal-install coverage: their graphql stage is a benign no-op).
    for pipeline in scenario.run:
        extra = PIPELINE_EXTRAS.get(pipeline)
        if extra is not None:
            required.add(extra)
    return tuple(sorted(required))
