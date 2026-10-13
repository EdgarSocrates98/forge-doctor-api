"""Spec 052 — ExpressAdapter + NestJsAdapter: golden + adversarial."""

from __future__ import annotations

from pathlib import Path

import framework_conformance as fc
from forge_doctor_api.analyzers.routes.javascript import (
    ExpressAdapter,
    NestJsAdapter,
)
from forge_doctor_api.core.context import ProjectContext

EXPRESS_APP = '''
const express = require("express");
const app = express();
const api = express.Router();

api.get("/items", listItems);
api.post("/items/:id", updateItem);
app.use("/v1", api);

// app.get("/commented", x);
/* app.delete("/gone", x) */
const fake = "app.put("/str/", x)";
app.get(`/tpl/${id}`, handler);
'''

NEST_APP = '''
import { Body, Controller, Delete, Get, Post, UseGuards } from "@nestjs/common";
import { AuthGuard } from "./auth";

@Controller("pets")
@UseGuards(AuthGuard)
export class PetsController {
  @Get(":id")
  findOne(@Param("id") id: string) {}

  @Post()
  create(@Body() dto: CreatePetDto) {}

  @Delete(`/tpl/${id}`)
  dynamic() {}
}
'''


def _ctx(tmp_path: Path, files: dict[str, str]):
    for name, body in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return ProjectContext.from_root(tmp_path)


def _scan(adapter, tmp_path: Path, files: dict[str, str]):
    ctx = _ctx(tmp_path, files)
    all_files = list(ctx.iter_files())
    return adapter.discover_routes(ctx, "svc", all_files)


def test_express_literal_routes_and_prefixes(tmp_path: Path) -> None:
    scan = _scan(ExpressAdapter(), tmp_path, {"server.js": EXPRESS_APP})
    got = sorted((r.method, r.path, r.handler) for r in scan.routes)
    assert got == [
        ("GET", "/v1/items", "listItems"),
        ("POST", "/v1/items/{id}", "updateItem"),
    ]


def test_express_adversarial_never_routes(tmp_path: Path) -> None:
    scan = _scan(ExpressAdapter(), tmp_path, {"server.js": EXPRESS_APP})
    paths = {r.path for r in scan.routes}
    assert "/commented" not in paths and "/gone" not in paths
    assert not any("str" in p for p in paths)
    assert any("literal route path" in u.missing
               for u in scan.unknowns)  # template literal


def test_express_detect_package_json(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {
        "package.json": '{"dependencies": {"express": "^4.0.0"}}'})
    assert ExpressAdapter().detect(ctx, list(ctx.iter_files()))


def test_nest_routes(tmp_path: Path) -> None:
    scan = _scan(NestJsAdapter(), tmp_path, {"pets.ts": NEST_APP})
    got = sorted((r.method, r.path, r.handler) for r in scan.routes)
    assert got == [
        ("GET", "/pets/{id}", "PetsController.findOne"),
        ("POST", "/pets", "PetsController.create"),
    ]
    assert any("literal route path" in u.missing
               for u in scan.unknowns)  # @Delete(`/tpl/${id}`)


def test_nest_auth_surface(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"pets.ts": NEST_APP})
    files = list(ctx.iter_files())
    auth = NestJsAdapter().discover_auth(ctx, files)
    assert any("UseGuards" in i.label for i in auth.items)


def test_nest_comments_cannot_route(tmp_path: Path) -> None:
    src = NEST_APP + '\n// @Get("/commented")\n// findFake() {}\n'
    scan = _scan(NestJsAdapter(), tmp_path, {"pets.ts": src})
    assert not any("commented" in r.path for r in scan.routes)


def test_node_modules_excluded(tmp_path: Path) -> None:
    scan = _scan(ExpressAdapter(), tmp_path, {
        "node_modules/pkg/index.js": EXPRESS_APP,
        "server.js": 'const e = require("express");\n'
                     'const app = e();\napp.get("/ok", h);\n',
    })
    assert {r.path for r in scan.routes} == {"/ok"}


def test_conformance(tmp_path: Path) -> None:
    for adapter in (ExpressAdapter(), NestJsAdapter()):
        report = fc.run_framework_conformance(adapter, tmp_path)
        for c in report.checks:
            assert c.passed, f"{adapter.name}.{c.name}: {c.detail}"
