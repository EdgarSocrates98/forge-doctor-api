"""Spec 051 — SpringBootAdapter: golden + adversarial Java scanning."""

from __future__ import annotations

from pathlib import Path

import framework_conformance as fc
from forge_doctor_api.analyzers.routes.spring import SpringBootAdapter
from forge_doctor_api.core.context import ProjectContext

CTL = '''
package com.acme.pets;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1")
public class PetsController {

    @GetMapping("/pets/{id}")
    public Pet findOne(@PathVariable Long id) { return null; }

    @PostMapping
    public Pet create(@RequestBody Pet body) { return null; }

    @RequestMapping(value = "/search", method = RequestMethod.GET)
    public Object search(@RequestParam String q) { return null; }
}
'''

ADVERSARIAL = '''
package com.acme.fake;
import org.springframework.web.bind.annotation.*;

// @GetMapping("/commented")
/* @PostMapping("/block-commented") */
@RestController
public class FakeController {

    String sample = "@DeleteMapping(\\"/in-a-string\\")";

    @GetMapping("/real")
    public Object real() { return null; }
}
'''

CONDITIONAL = '''
package com.acme.cond;
import org.springframework.web.bind.annotation.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;

@RestController
@ConditionalOnProperty(name = "feature.pets", havingValue = "true")
public class ConditionalController {
    @GetMapping("/maybe")
    public Object maybe() { return null; }
}
'''

DYNAMIC = '''
package com.acme.dyn;
import org.springframework.web.bind.annotation.*;

@RestController
public class DynamicController {
    private static final String BASE = "/users";

    @GetMapping(path = BASE)
    public Object all() { return null; }
}
'''


def _ctx(tmp_path: Path, files: dict[str, str]):
    for name, body in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return ProjectContext.from_root(tmp_path)


def _scan(tmp_path: Path, files: dict[str, str]):
    ctx = _ctx(tmp_path, files)
    all_files = list(ctx.iter_files())
    return SpringBootAdapter().discover_routes(ctx, "svc", all_files)


def test_golden_routes(tmp_path: Path) -> None:
    scan = _scan(tmp_path, {"PetsController.java": CTL})
    got = sorted((r.method, r.path, r.handler) for r in scan.routes)
    assert got == [
        ("GET", "/api/v1/pets/{id}", "PetsController.findOne"),
        ("GET", "/api/v1/search", "PetsController.search"),
        ("POST", "/api/v1", "PetsController.create"),
    ]
    find = next(r for r in scan.routes if r.handler.endswith("findOne"))
    assert any(p.name == "id" and p.location_in == "path"
               for p in find.parameters)


def test_comments_and_strings_cannot_route(tmp_path: Path) -> None:
    scan = _scan(tmp_path, {"Fake.java": ADVERSARIAL})
    paths = {r.path for r in scan.routes}
    assert paths == {"/real"}


def test_conditional_route_is_flagged(tmp_path: Path) -> None:
    scan = _scan(tmp_path, {"Cond.java": CONDITIONAL})
    assert any(r.path == "/maybe" for r in scan.routes)
    assert any("Conditional" in u.missing or "conditional" in u.missing
               or "unconditional" in u.missing for u in scan.unknowns)


def test_dynamic_path_is_unknown(tmp_path: Path) -> None:
    scan = _scan(tmp_path, {"Dyn.java": DYNAMIC})
    assert not scan.routes
    assert any("literal route path" in u.missing
               for u in scan.unknowns)


def test_requestmapping_without_method_is_unknown(tmp_path: Path) -> None:
    src = CTL.replace(
        "method = RequestMethod.GET", "")
    scan = _scan(tmp_path, {"Ctl.java": src})
    assert not any("search" in r.handler for r in scan.routes)


def test_vendored_and_generated_excluded(tmp_path: Path) -> None:
    scan = _scan(tmp_path, {
        "generated/Ctl.java": CTL,
        "src/Ctl.java": ADVERSARIAL,
    })
    assert {r.path for r in scan.routes} == {"/real"}


def test_detect_manifest_and_import(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {
        "pom.xml": "<dep>org.springframework.boot</dep>"})
    assert SpringBootAdapter().detect(ctx, list(ctx.iter_files()))
    ctx2 = _ctx(tmp_path / "other", {"x.txt": "nothing"})
    assert not SpringBootAdapter().detect(ctx2, list(ctx2.iter_files()))


def test_surfaces(tmp_path: Path) -> None:
    src = CTL + '''
@ControllerAdvice
class Advice { @ExceptionHandler(Exception.class) void h() {} }
'''
    ctx = _ctx(tmp_path, {"Ctl.java": src})
    files = list(ctx.iter_files())
    adapter = SpringBootAdapter()
    assert adapter.discover_error_handlers(ctx, files).items
    assert adapter.discover_schemas(ctx, files).items  # @RequestBody


def test_conformance(tmp_path: Path) -> None:
    report = fc.run_framework_conformance(SpringBootAdapter(), tmp_path)
    for c in report.checks:
        assert c.passed, f"{c.name}: {c.detail}"
