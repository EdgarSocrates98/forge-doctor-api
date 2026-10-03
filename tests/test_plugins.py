"""Plugin SDK + trust boundary tests (spec 027, §131-§132).

UNTRUSTED plugins are listed in the registry but `load_plugin` refuses
them — the boundary is binding, not advisory.
"""

from __future__ import annotations

import pytest

from forge_doctor_api.analyzers.routes import FastApiAdapter
from forge_doctor_api.core.models import ModelError
from forge_doctor_api.plugins import (
    FrameworkAdapter,
    PluginDescriptor,
    PluginRegistry,
    RuntimeAdapter,
    TrustClass,
    describe_untrusted,
    load_plugin,
)


def test_fastapi_adapter_satisfies_framework_protocol() -> None:
    """Structural conformance — the builtin adapter is a FrameworkAdapter."""
    assert isinstance(FastApiAdapter(), FrameworkAdapter)


def test_otlp_adapter_satisfies_runtime_protocol() -> None:
    from forge_doctor_api.analyzers.runtime.otlp import OtlpJsonAdapter

    assert isinstance(OtlpJsonAdapter(), RuntimeAdapter)


def test_trust_classes() -> None:
    assert set(TrustClass) == {
        TrustClass.BUILTIN, TrustClass.SIGNED,
        TrustClass.APPROVED_LOCAL, TrustClass.UNTRUSTED,
    }


def test_builtin_loads_inside_package() -> None:
    mod = load_plugin(PluginDescriptor(
        name="fastapi",
        module="forge_doctor_api.analyzers.routes.fastapi",
        trust=TrustClass.BUILTIN,
    ))
    assert mod.__name__ == "forge_doctor_api.analyzers.routes.fastapi"


def test_builtin_rejects_outside_package() -> None:
    with pytest.raises(ModelError, match="forge_doctor_api"):
        load_plugin(PluginDescriptor(
            name="evil", module="os", trust=TrustClass.BUILTIN,
        ))


def test_untrusted_never_loaded() -> None:
    desc = PluginDescriptor(
        name="random-plugin", module="json", trust=TrustClass.UNTRUSTED,
    )
    with pytest.raises(ModelError, match="UNTRUSTED"):
        load_plugin(desc)


def test_registry_lists_but_does_not_load_untrusted() -> None:
    registry = PluginRegistry(plugins=(
        PluginDescriptor(
            name="a", module="json", trust=TrustClass.APPROVED_LOCAL,
        ),
        PluginDescriptor(
            name="b", module="nonexistent", trust=TrustClass.UNTRUSTED,
        ),
    ))
    assert [p.name for p in registry.loadable] == ["a"]
    assert [p.name for p in registry.untrusted] == ["b"]
    unknowns = describe_untrusted(registry)
    assert len(unknowns) == 1 and unknowns[0].subject == "b"


def test_approved_local_loads_plain_module() -> None:
    mod = load_plugin(PluginDescriptor(
        name="stdlib", module="json", trust=TrustClass.APPROVED_LOCAL,
    ))
    assert mod.__name__ == "json"


def test_bad_module_raises_model_error() -> None:
    with pytest.raises(ModelError, match="failed to import"):
        load_plugin(PluginDescriptor(
            name="missing", module="no.such.module",
            trust=TrustClass.APPROVED_LOCAL,
        ))
