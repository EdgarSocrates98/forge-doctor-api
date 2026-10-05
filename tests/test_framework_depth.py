"""Spec 078 — framework depth: capability surfaces beyond routes.

Each adapter must evidence the four capability dimensions where
idiom-static evidence exists — auth-dependency, error contract,
validation, client injection — and answer the rest with explicit
`UnknownFact`s, never silence. Commented-out or string-literal
idioms must produce nothing.
"""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

from forge_doctor_api.analyzers.routes.fastapi import FastApiAdapter
from forge_doctor_api.analyzers.routes.javascript import (
    ExpressAdapter,
    NestJsAdapter,
)
from forge_doctor_api.analyzers.routes.spring import SpringBootAdapter
from forge_doctor_api.core.context import ProjectContext


def _ctx(files: dict[str, str]) -> tuple[ProjectContext, list[str]]:
    root = Path(tempfile.mkdtemp())
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    return ProjectContext.from_root(root), list(files)


def _kinds(result) -> set[str]:
    return {i.kind for i in result.items}


class TestFastApiDepth:
    def test_error_contract_includes_raised_http_exceptions(self):
        ctx, files = _ctx({"main.py": """
            from fastapi import FastAPI, HTTPException
            app = FastAPI()
            @app.exception_handler(ValueError)
            async def on_value(request, exc): ...
            @app.get("/pets/{pet_id}")
            def pet(pet_id: int):
                raise HTTPException(status_code=404, detail="not found")
        """})
        r = FastApiAdapter().discover_error_handlers(ctx, files)
        kinds = _kinds(r)
        assert "error-handler" in kinds
        assert "http-error" in kinds
        labels = {i.label for i in r.items}
        assert "raise HTTPException(404)" in labels
        assert "ValueError -> on_value" in labels

    def test_auth_validation_and_injection(self):
        ctx, files = _ctx({"main.py": """
            from fastapi import Depends, FastAPI, Query, Security
            from fastapi.security import OAuth2PasswordBearer
            app = FastAPI()
            oauth = OAuth2PasswordBearer(tokenUrl="token")
            def get_db(): ...
            @app.get("/pets")
            def pets(q: str = Query(default=None, min_length=3),
                     tok: str = Security(oauth),
                     db=Depends(get_db)): ...
        """})
        a = FastApiAdapter()
        assert "auth-dependency" in _kinds(a.discover_auth(ctx, files))
        assert "bound-param" in _kinds(a.discover_validation(ctx, files))
        deps = a.discover_dependencies(ctx, files)
        assert any("get_db" in i.label for i in deps.items)

    def test_absent_idiom_is_explicit_unknown(self):
        ctx, files = _ctx({"main.py": """
            from fastapi import FastAPI
            app = FastAPI()
            @app.get("/ok")
            def ok(): return {}
        """})
        r = FastApiAdapter().discover_validation(ctx, files)
        assert not r.items
        assert r.unknowns and "validation" in r.unknowns[0].subject


class TestSpringDepth:
    _CTRL = """
        package demo;
        import org.springframework.web.bind.annotation.*;
        import org.springframework.security.access.prepost.PreAuthorize;
        import javax.validation.Valid;
        @RestController
        @RequestMapping("/api")
        class PetController {
          @PostMapping("/pets")
          @PreAuthorize("hasRole('ADMIN')")
          public Pet addPet(@Valid @RequestBody PetCreateDto body) {
            return null;
          }
        }
    """

    def test_request_body_type_is_schema_evidence(self):
        ctx, files = _ctx({"PetController.java": self._CTRL})
        r = SpringBootAdapter().discover_schemas(ctx, files)
        labels = {i.label for i in r.items}
        assert "PetCreateDto" in labels
        assert "@RequestBody" in labels
        assert "request-schema-type" in _kinds(r)

    def test_generic_body_type_preserved(self):
        ctx, files = _ctx({"C.java": """
            package demo;
            import org.springframework.web.bind.annotation.*;
            import java.util.List;
            @RestController
            class C {
              @PutMapping("/bulk")
              public Pet put(@RequestBody List<PetDto> pets) {
                return null;
              }
            }
        """})
        r = SpringBootAdapter().discover_schemas(ctx, files)
        assert "List<PetDto>" in {i.label for i in r.items}

    def test_auth_validation_dependencies(self):
        ctx, files = _ctx({"PetController.java": self._CTRL})
        sp = SpringBootAdapter()
        assert "auth-expression" in _kinds(sp.discover_auth(ctx, files))
        assert "validation-marker" in _kinds(
            sp.discover_validation(ctx, files))


class TestExpressDepth:
    _APP = """
        const express = require("express");
        const passport = require("passport");
        const { body, validationResult } = require("express-validator");
        const app = express();
        app.use(passport.initialize());
        function errHandler(err, req, res, next) {
          res.status(500).send("x");
        }
        app.get("/pets", passport.authenticate("jwt"),
                body("name").isString(),
                (req, res) => res.send(req.app.get("db")));
        app.use((err, req, res, next) => res.status(400).end());
        app.use(errHandler);
        app.set("db", pool);
    """

    def test_auth_middleware_and_module(self):
        ctx, files = _ctx({"app.js": self._APP})
        r = ExpressAdapter().discover_auth(ctx, files)
        kinds = _kinds(r)
        assert "auth-module" in kinds
        assert "auth-middleware" in kinds
        assert "passport.authenticate()" in {i.label for i in r.items}

    def test_validator_module_gates_calls(self):
        """`body(` is only evidence when express-validator is imported —
        a bare `body(x)` in a file without the import proves nothing."""
        ctx, files = _ctx({
            "app.js": self._APP,
            "other.js": """
                const x = require("x");
                function body(n) { return n; }
                body("fake").isString();
            """,
        })
        r = ExpressAdapter().discover_validation(ctx, files)
        calls = [i for i in r.items if i.kind == "validation-call"]
        assert calls and all(
            i.location.path.endswith("app.js") for i in calls)
        assert "express-validator" in {i.label for i in r.items
                                       if i.kind == "validation-module"}

    def test_err_first_middleware_and_registration(self):
        ctx, files = _ctx({"app.js": self._APP})
        r = ExpressAdapter().discover_error_handlers(ctx, files)
        kinds = _kinds(r)
        assert "error-middleware" in kinds
        assert "error-middleware-registration" in kinds
        assert "inline-error-middleware" in kinds

    def test_registry_dependency_idiom(self):
        ctx, files = _ctx({"app.js": self._APP})
        r = ExpressAdapter().discover_dependencies(ctx, files)
        labels = {i.label for i in r.items}
        assert 'app.set("db")' in labels
        assert 'req.app.get("db")' in labels
        assert {"app-registry", "registry-read"} <= _kinds(r)

    def test_middleware_args_are_top_level_only(self):
        """Identifiers inside an inline arrow body must not leak into
        the middleware surface."""
        ctx, files = _ctx({"app.js": self._APP})
        r = ExpressAdapter().discover_middleware(ctx, files)
        labels = {i.label for i in r.items}
        assert "errHandler" in labels
        assert "passport.initialize()" in labels
        assert not labels & {"err", "req", "res", "next", "res.status"}


class TestNestJsDepth:
    _CTRL = """
        import { Controller, Get, Post, Body, UseGuards }
          from '@nestjs/common';
        import { CatsService } from './cats.service';
        import { JwtAuthGuard } from './auth.guard';
        import { CreateCatDto } from './dto';
        @Controller('cats')
        export class CatsController {
          constructor(private readonly cats: CatsService) {}
          @Get()
          @UseGuards(JwtAuthGuard)
          findAll() { return this.cats.all(); }
          @Post()
          create(@Body() dto: CreateCatDto) { return this.cats.add(dto); }
        }
    """

    def test_constructor_injection_is_dependency_evidence(self):
        ctx, files = _ctx({"cats.controller.ts": self._CTRL})
        r = NestJsAdapter().discover_dependencies(ctx, files)
        assert ("injected-provider", "CatsService") in {
            (i.kind, i.label) for i in r.items}

    def test_body_param_type_is_schema_evidence(self):
        ctx, files = _ctx({"cats.controller.ts": self._CTRL})
        r = NestJsAdapter().discover_schemas(ctx, files)
        assert "CreateCatDto" in {i.label for i in r.items}
        assert "request-schema-type" in _kinds(r)

    def test_absent_error_idiom_is_explicit_unknown(self):
        ctx, files = _ctx({"cats.controller.ts": self._CTRL})
        r = NestJsAdapter().discover_error_handlers(ctx, files)
        assert not r.items
        assert r.unknowns


class TestAdversarial:
    """Commented-out and string-literal idioms are never evidence."""

    def test_commented_express_calls_produce_nothing(self):
        ctx, files = _ctx({"app.js": """
            const express = require("express");
            const app = express();
            // app.use(passport.initialize());
            // const passport = require("passport");
            const note = "app.set('db', x) jwt.verify(t, s)";
            /* passport.authenticate("jwt") */
            app.get("/ok", (req, res) => res.send("ok"));
        """})
        ex = ExpressAdapter()
        for surface in ("discover_auth", "discover_validation",
                        "discover_dependencies", "discover_error_handlers"):
            r = getattr(ex, surface)(ctx, files)
            assert not r.items, f"{surface}: phantom evidence {r.items}"
            assert r.unknowns

    def test_commented_java_annotations_produce_nothing(self):
        ctx, files = _ctx({"C.java": """
            package demo;
            import org.springframework.web.bind.annotation.*;
            @RestController
            class C {
              // @PreAuthorize("hasRole('ADMIN')")
              String s = "@RequestBody FakeDto f @Valid";
              @GetMapping("/ok")
              public Pet ok() { return null; }
            }
        """})
        sp = SpringBootAdapter()
        for surface in ("discover_auth", "discover_validation",
                        "discover_schemas"):
            r = getattr(sp, surface)(ctx, files)
            assert not r.items, f"{surface}: phantom evidence {r.items}"
            assert r.unknowns

    def test_string_literal_route_strings_stay_inert(self):
        ctx, files = _ctx({"app.js": """
            const express = require("express");
            const app = express();
            const doc = "router.get('/pets', handler)";
        """})
        scan = ExpressAdapter().discover_routes(ctx, "svc", files)
        assert not scan.routes

