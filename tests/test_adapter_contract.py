"""Spec 050 — FrameworkAdapter contract: §39 surface + registry."""

from __future__ import annotations

from pathlib import Path

import framework_conformance as fc
from forge_doctor_api.analyzers.routes import (
    FastApiAdapter,
    FrameworkAdapter,
    available_adapters,
)
from forge_doctor_api.analyzers.routes.javascript import (
    ExpressAdapter,
    NestJsAdapter,
)
from forge_doctor_api.analyzers.routes.spring import SpringBootAdapter
from forge_doctor_api.core.context import ProjectContext

FASTAPI_APP = '''
from fastapi import FastAPI, Depends

app = FastAPI()

@app.get("/items")
def list_items():
    return []
'''

SPRING_CTL = '''
package x;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping("/api")
class Ctl {
    @GetMapping("/users")
    public Object users() { return null; }
}
'''

EXPRESS_APP = '''
const express = require("express");
const app = express();
app.get("/items", listItems);
'''

NEST_CTL = '''
import { Controller, Get } from "@nestjs/common";
@Controller("pets")
export class Ctl { @Get() list() {} }
'''


def _ctx(tmp_path: Path, files: dict[str, str]):
    for name, body in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return ProjectContext.from_root(tmp_path)


def test_adapter_is_protocol_runtime_checkable() -> None:
    for adapter in (FastApiAdapter(), SpringBootAdapter(),
                    ExpressAdapter(), NestJsAdapter()):
        assert isinstance(adapter, FrameworkAdapter)


def test_available_adapters_fastapi(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"app.py": FASTAPI_APP})
    names = {a.name for a in available_adapters(
        ctx, list(ctx.iter_files()))}
    assert names == {"fastapi"}


def test_available_adapters_multi_language(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {
        "app.py": FASTAPI_APP, "Ctl.java": SPRING_CTL,
        "server.js": EXPRESS_APP, "ctl.ts": NEST_CTL,
    })
    names = {a.name for a in available_adapters(
        ctx, list(ctx.iter_files()))}
    assert names == {"express", "fastapi", "nestjs", "spring"}


def test_available_adapters_empty_project(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"readme.md": "# nothing"})
    adapters = available_adapters(ctx, list(ctx.iter_files()))
    assert adapters == ()


def test_unknown_framework_never_guesses(tmp_path: Path) -> None:
    # Rails-looking Ruby: no adapter should match or fabricate routes.
    ctx = _ctx(tmp_path, {"routes.rb": "Rails.application.routes.draw\n"
                          "  get '/pets', to: 'pets#index'\nend\n"})
    assert available_adapters(ctx, list(ctx.iter_files())) == ()


def test_conformance_all_builtin_adapters(tmp_path: Path) -> None:
    for factory in (FastApiAdapter, SpringBootAdapter,
                    ExpressAdapter, NestJsAdapter):
        report = fc.run_framework_conformance(factory(), tmp_path)
        for check in report.checks:
            assert check.passed, f"{report.adapter}.{check.name}: {check.detail}"


def test_surface_methods_return_unknown_on_empty(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"app.py": FASTAPI_APP})
    files = list(ctx.iter_files())
    result = FastApiAdapter().discover_error_handlers(ctx, files)
    assert result.items == ()
    assert result.unknowns  # absence is explicit, never silent


def test_fastapi_surface_extraction(tmp_path: Path) -> None:
    app = '''
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()
app.add_middleware(GZipMiddleware)

@app.exception_handler(ValueError)
def on_value_error():
    return JSONResponse({})

@app.get("/items")
def list_items(dep=Depends(get_db)):
    return []
'''
    ctx = _ctx(tmp_path, {"app.py": app})
    files = list(ctx.iter_files())
    adapter = FastApiAdapter()
    deps = adapter.discover_dependencies(ctx, files)
    assert any("get_db" in i.label or "Depends" in i.label
               for i in deps.items)
    handlers = adapter.discover_error_handlers(ctx, files)
    assert any("ValueError" in i.label for i in handlers.items)


def test_scan_still_routes_through_registry(tmp_path: Path) -> None:
    """Multi-framework project: every adapter's routes merge."""
    ctx = _ctx(tmp_path, {
        "app.py": FASTAPI_APP, "Ctl.java": SPRING_CTL})
    adapters = available_adapters(ctx, list(ctx.iter_files()))
    routes = []
    for a in adapters:
        routes += list(a.discover_routes(ctx, "svc").routes)
    assert len(routes) == 2
    assert {r.framework for r in routes} == {"fastapi", "spring"}
