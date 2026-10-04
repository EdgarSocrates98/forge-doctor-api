"""Express + NestJS adapters (§45-§46): zero-dependency JS/TS scanner.

Same adversarial posture as the Spring adapter: `strip_source` blanks
comments and string interiors, so `app.get(` inside a comment or a
literal can never register a route — while the literal path inside a
real call is still resolvable.

Two modes sharing one parse:

- `NestJsAdapter` — decorator state machine (`@Controller(prefix)` +
  `@Get`/`@Post`/... on methods), like Spring;
- `ExpressAdapter` — call-expression extraction
  (`var.(get|post|put|delete|patch|all|use)(literal, ...)`) with
  literal-only paths and `use(prefix, router)` composition where both
  sides are statically literal.

Template literals (`` `/pets/${id}` ``) and non-literal args record
`UnknownFact`s — interpolated paths are not static evidence (§46, §49).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from forge_doctor_api.analyzers.routes.adapter import (
    FrameworkAdapter,
    is_skippable,
    unknown_surface,
)
from forge_doctor_api.analyzers.routes.model import (
    Attribution,
    RouteModel,
    RouteScan,
    SurfaceItem,
    SurfaceResult,
)
from forge_doctor_api.analyzers.routes.spring import _join, _norm
from forge_doctor_api.analyzers.routes.textscan import (
    StrippedSource,
    line_of,
    strip_source,
)
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    SourceLocation,
    UnknownFact,
)

_JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
_NEST_METHODS = {
    "Get": "GET", "Post": "POST", "Put": "PUT", "Delete": "DELETE",
    "Patch": "PATCH", "Options": "OPTIONS", "Head": "HEAD", "All": "ALL",
}
_EXPRESS_METHODS = {
    "get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE",
    "patch": "PATCH", "options": "OPTIONS", "head": "HEAD", "all": "ALL",
}

_DECORATOR_RE = re.compile(r"@([A-Za-z_]\w*)\s*(?:\()?", re.ASCII)
_CLASS_RE = re.compile(
    r"(?:^|[\s{;])(?:export\s+|abstract\s+)*class\s+([A-Za-z_]\w*)")
_METHOD_BODY_RE = re.compile(r"\s*(?::\s*[\w<>\[\]|&.,\s]+)?\s*\{")
_NOT_METHODS = {
    "if", "for", "while", "switch", "catch", "function", "return",
    "class", "constructor", "require", "import", "export",
}
_IMPORT_RE = re.compile(
    r"(?:import[^;]*?from\s*|require\s*\()\s*")
_CALL_RE = re.compile(
    r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(")
_VAR_RE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=")


@dataclass(frozen=True)
class _Decorator:
    name: str
    start: int
    end: int
    literals: tuple[str, ...]


@dataclass(frozen=True)
class _Call:
    name: str
    start: int
    open_paren: int
    end: int
    literals: tuple[tuple[int, int, str], ...]


@dataclass
class _JsFile:
    path: str
    stripped: StrippedSource
    decorators: list[_Decorator] = field(default_factory=list)
    classes: list[tuple[int, str]] = field(default_factory=list)
    methods: list[tuple[int, str, int, str]] = field(
        default_factory=list)  # (start, name, end, params_text)
    calls: list[_Call] = field(default_factory=list)
    imports: list[tuple[int, str]] = field(default_factory=list)
    vars: dict[str, int] = field(default_factory=dict)


def _balanced(safe: str, start: int) -> int:
    depth = 0
    for k in range(start, len(safe)):
        if safe[k] == "(":
            depth += 1
        elif safe[k] == ")":
            depth -= 1
            if depth == 0:
                return k + 1
    return len(safe)


def _interpolated(value: str) -> bool:
    return "${" in value or "`" in value


def _parse_js(path: str, text: str) -> _JsFile:
    stripped = strip_source(text)
    jf = _JsFile(path=path, stripped=stripped)
    for m in _DECORATOR_RE.finditer(stripped.safe):
        end = m.end()
        if stripped.safe[m.end() - 1] == "(":
            end = _balanced(stripped.safe, m.end() - 1)
        lits = tuple(
            lit[2] for lit in stripped.literals
            if m.end() <= lit[0] < end)
        jf.decorators.append(_Decorator(m.group(1), m.start(), end, lits))
    for m in _CLASS_RE.finditer(stripped.safe):
        jf.classes.append((m.start(), m.group(1)))
    for m in _CALL_RE.finditer(stripped.safe):
        open_paren = m.end() - 1
        end = _balanced(stripped.safe, open_paren)
        call_lits = tuple(
            lit for lit in stripped.literals
            if open_paren < lit[0] < end)
        jf.calls.append(_Call(
            m.group(1), m.start(), open_paren, end, call_lits))
    # Methods = call-shapes whose balanced `)` is followed by `{`
    # (optionally after a `: ReturnType`). A decorator call like
    # `@Get(":id")` is followed by the real method decl, so it can
    # never be mistaken for one.
    for call in jf.calls:
        body_m = _METHOD_BODY_RE.match(stripped.safe, call.end)
        name = call.name.rsplit(".", 1)[-1]
        if body_m and name not in _NOT_METHODS:
            params = stripped.text[call.open_paren + 1:call.end - 1]
            jf.methods.append((call.start, name, call.end, params))
    for m in _IMPORT_RE.finditer(stripped.safe):
        lit = stripped.literal_at(m.end())
        if lit is not None:
            jf.imports.append((m.start(), lit))
    for m in _VAR_RE.finditer(stripped.safe):
        jf.vars[m.group(1)] = m.end()
    return jf


def _loc(path: str, text: str, pos: int) -> SourceLocation:
    return SourceLocation(path=path, line=line_of(text, pos))


def _norm_js(path: str) -> str:
    """JS route path -> canonical template (`:id` segments -> `{id}`)."""
    out = re.sub(r":([A-Za-z_]\w*)", r"{\1}", _norm(path))
    return out.rstrip("/") or "/"


def _package_deps(context: ProjectContext, files: Sequence[str]) -> set[str]:
    deps: set[str] = set()
    for f in files:
        if f.rsplit("/", 1)[-1] != "package.json":
            continue
        try:
            data = json.loads(context.read_text(f))
        except Exception:
            continue
        for section in ("dependencies", "devDependencies",
                        "peerDependencies"):
            deps.update(data.get(section) or {})
    return deps


class _JsBase(FrameworkAdapter):
    """Shared parse/detect/surface machinery for JS-family adapters."""

    framework = "javascript"
    file_pattern = "**/*.ts"

    def _files(
        self, context: ProjectContext, files: Sequence[str] | None
    ) -> list[str]:
        src = list(files) if files is not None else [
            f for pat in ("**/*.js", "**/*.ts", "**/*.jsx",
                          "**/*.tsx", "**/*.mjs", "**/*.cjs")
            for f in context.iter_files(pat)]
        return sorted(
            f for f in src
            if f.endswith(_JS_SUFFIXES)
            and not f.endswith(".d.ts")
            and not is_skippable(f))

    def _parsed(
        self, context: ProjectContext, files: Sequence[str] | None
    ) -> list[_JsFile]:
        out: list[_JsFile] = []
        for rel in self._files(context, files):
            try:
                out.append(_parse_js(rel, context.read_text(rel)))
            except Exception:
                continue
        return out

    def _surface_items(
        self,
        context: ProjectContext,
        files: Sequence[str],
        kinds: dict[str, str],
    ) -> tuple[SurfaceItem, ...]:
        items: list[SurfaceItem] = []
        for jf in self._parsed(context, files):
            if not self._file_relevant(jf):
                continue
            for dec in jf.decorators:
                kind = kinds.get(dec.name)
                if kind is None:
                    continue
                lit = dec.literals[0] if dec.literals else ""
                items.append(SurfaceItem(
                    label=f"@{dec.name}({lit})" if lit
                    else f"@{dec.name}",
                    kind=kind,
                    location=_loc(jf.path, jf.stripped.text, dec.start)))
        return tuple(sorted(set(items), key=lambda i: (
            i.kind, i.label, i.location.path, i.location.line or 0)))

    def _file_relevant(self, jf: _JsFile) -> bool:
        return bool(jf.imports)

    def _surface(
        self, surface: str, context: ProjectContext,
        files: Sequence[str], kinds: dict[str, str],
    ) -> SurfaceResult:
        items = self._surface_items(context, files, kinds)
        if not items:
            return unknown_surface(surface, self.framework)
        return SurfaceResult(surface=surface, items=items)

    def discover_auth(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        return self._surface("auth", context, files, {
            "UseGuards": "guard", "SetMetadata": "metadata",
            "Roles": "roles", "Public": "public-marker",
        })

    def discover_schemas(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        items: list[SurfaceItem] = []
        for jf in self._parsed(context, files):
            if not self._file_relevant(jf):
                continue
            for dec in jf.decorators:
                if dec.name != "Body":
                    continue
                items.append(SurfaceItem(
                    label="@Body()", kind="request-schema",
                    location=_loc(jf.path, jf.stripped.text, dec.start)))
        if not items:
            return unknown_surface("schemas", self.framework)
        return SurfaceResult(surface="schemas", items=tuple(
            sorted(items, key=lambda i: (
                i.location.path, i.location.line or 0))))

    def discover_dependencies(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        return self._surface("dependencies", context, files, {
            "Inject": "injection", "Injectable": "provider",
        })

    def discover_middleware(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        return self._surface("middleware", context, files, {
            "UseInterceptors": "interceptor",
            "UsePipes": "pipe",
            "UseFilters": "filter",
            "Middleware": "middleware-marker",
        })

    def discover_error_handlers(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        return self._surface("error_handlers", context, files, {
            "Catch": "exception-filter",
            "UseFilters": "filter",
        })

    def discover_validation(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        return self._surface("validation", context, files, {
            "UsePipes": "pipe",
            "IsString": "constraint", "IsInt": "constraint",
            "IsOptional": "constraint", "Min": "constraint",
            "Max": "constraint", "Length": "constraint",
        })

    def discover_serialization(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        return self._surface("serialization", context, files, {
            "SerializeOptions": "serialization",
            "Transform": "transform",
        })

    def discover_client_calls(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        items: list[SurfaceItem] = []
        for jf in self._parsed(context, files):
            safe = jf.stripped.safe
            for m in re.finditer(
                r"\b(?:axios\.[a-z]+|fetch|got\.[a-z]+|request)\s*\(",
                safe):
                items.append(SurfaceItem(
                    label=m.group(0).rstrip(" ("), kind="http-client-call",
                    location=_loc(jf.path, jf.stripped.text, m.start())))
        if not items:
            return unknown_surface("client_calls", self.framework)
        return SurfaceResult(surface="client_calls", items=tuple(
            sorted(items, key=lambda i: (
                i.label, i.location.path, i.location.line or 0))))


class NestJsAdapter(_JsBase):
    """NestJS: `@Controller(prefix)` + method decorators (§45)."""

    name = "nestjs"
    framework = "nestjs"

    def _file_relevant(self, jf: _JsFile) -> bool:
        return any("@nestjs/" in imp for _, imp in jf.imports)

    def detect(
        self, context: ProjectContext, files: Sequence[str]
    ) -> bool:
        if any(d.startswith("@nestjs/") or d == "@nestjs/common"
               for d in _package_deps(context, files)):
            return True
        for jf in self._parsed(context, files):
            if self._file_relevant(jf) and any(
                    d.name == "Controller" for d in jf.decorators):
                return True
        return False

    def attribute(
        self, context: ProjectContext, files: Sequence[str]
    ) -> tuple[Attribution, ...]:
        attrs: list[Attribution] = []
        for jf in self._parsed(context, files):
            marker = next(
                (d for d in jf.decorators if d.name == "Controller"),
                None)
            if self._file_relevant(jf) and marker is not None:
                attrs.append(Attribution(
                    framework=self.framework, path=jf.path,
                    evidence=(Evidence(
                        kind=EvidenceKind.STATIC, source=jf.path,
                        summary="imports @nestjs/* and declares "
                        "@Controller",
                        line=line_of(jf.stripped.text, marker.start)),)))
        return tuple(attrs)

    def discover_routes(
        self,
        context: ProjectContext,
        service: str,
        files: Sequence[str] | None = None,
    ) -> RouteScan:
        routes: list[RouteModel] = []
        attributions: list[Attribution] = []
        unknowns: list[UnknownFact] = []
        for jf in self._parsed(context, files):
            if not self._file_relevant(jf):
                continue
            attributions.extend(self.attribute(
                context, [jf.path]) or ())
            decls = sorted(
                [(c[0], "class", c[1], "") for c in jf.classes]
                + [(m[0], "method", m[1], m[3]) for m in jf.methods])
            prev_end, class_name, prefix = 0, "", ""
            controller = False
            for start, kind, name, _params in decls:
                decs = [
                    d for d in jf.decorators
                    if prev_end < d.start < start]
                if kind == "class":
                    class_name = name
                    ctrl = next(
                        (d for d in decs if d.name == "Controller"),
                        None)
                    controller = ctrl is not None
                    if ctrl and ctrl.literals:
                        prefix = _norm(ctrl.literals[0])
                    elif ctrl is not None:
                        prefix = ""
                    continue
                if not controller:
                    prev_end = start
                    continue
                loc = _loc(jf.path, jf.stripped.text, start)
                for dec in decs:
                    method = _NEST_METHODS.get(dec.name)
                    if method is None:
                        continue
                    subs = dec.literals
                    dyn = [lit for lit in subs if _interpolated(lit)]
                    if dyn:
                        unknowns.append(UnknownFact(
                            subject=f"{jf.path}#L{loc.line}",
                            missing="literal route path",
                            resolution="template-literal paths are "
                            "dynamic; route cannot be evidenced"))
                        continue
                    static = tuple(s for s in subs
                                   if not _interpolated(s)) or ("",)
                    for sub in sorted(set(static)):
                        routes.append(RouteModel(
                            framework=self.framework, service=service,
                            method=method,
                            path=_norm_js(_join(prefix, sub)) if sub
                            else (_norm_js(prefix) if prefix else "/"),
                            handler=f"{class_name}.{name}",
                            source_location=loc))
                prev_end = start
        return RouteScan(
            service=service,
            routes=tuple(sorted(set(routes), key=lambda r: (
                r.method, r.path, r.handler))),
            attributions=tuple(sorted(set(attributions),
                                      key=lambda a: a.path)),
            unknowns=tuple(sorted(set(unknowns), key=lambda u: (
                u.subject, u.missing))))


class ExpressAdapter(_JsBase):
    """Express: literal `app|router.METHOD()` calls (§45)."""

    name = "express"
    framework = "express"

    def _file_relevant(self, jf: _JsFile) -> bool:
        return any(imp == "express" for _, imp in jf.imports) or any(
            c.name in ("express", "express.Router") for c in jf.calls)

    def detect(
        self, context: ProjectContext, files: Sequence[str]
    ) -> bool:
        if "express" in _package_deps(context, files):
            return True
        return any(
            self._file_relevant(jf)
            for jf in self._parsed(context, files))

    def attribute(
        self, context: ProjectContext, files: Sequence[str]
    ) -> tuple[Attribution, ...]:
        attrs: list[Attribution] = []
        for jf in self._parsed(context, files):
            creates = [
                c for c in jf.calls
                if c.name in ("express", "express.Router")]
            if self._file_relevant(jf) and creates:
                attrs.append(Attribution(
                    framework=self.framework, path=jf.path,
                    evidence=(Evidence(
                        kind=EvidenceKind.STATIC, source=jf.path,
                        summary="imports/requires express and "
                        "instantiates app/router",
                        line=line_of(
                            jf.stripped.text, creates[0].start)),)))
        return tuple(attrs)

    def discover_routes(
        self,
        context: ProjectContext,
        service: str,
        files: Sequence[str] | None = None,
    ) -> RouteScan:
        routes: list[RouteModel] = []
        attributions: list[Attribution] = []
        unknowns: list[UnknownFact] = []
        for jf in self._parsed(context, files):
            if not self._file_relevant(jf):
                continue
            attr = self.attribute(context, [jf.path])
            attributions.extend(attr or ())
            self._routes_file(jf, service, routes, unknowns)
        return RouteScan(
            service=service,
            routes=tuple(sorted(set(routes), key=lambda r: (
                r.method, r.path, r.handler))),
            attributions=tuple(sorted(set(attributions),
                                      key=lambda a: a.path)),
            unknowns=tuple(sorted(set(unknowns), key=lambda u: (
                u.subject, u.missing))))

    def _routes_file(
        self,
        jf: _JsFile,
        service: str,
        routes: list[RouteModel],
        unknowns: list[UnknownFact],
    ) -> None:
        text = jf.stripped.text
        receivers = self._receivers(jf)
        prefixes = self._prefixes(jf, receivers, unknowns)
        for call in jf.calls:
            recv, _, meth = call.name.rpartition(".")
            verb = _EXPRESS_METHODS.get(meth)
            if verb is None or recv not in receivers:
                continue
            loc = _loc(jf.path, text, call.start)
            if not call.literals:
                unknowns.append(UnknownFact(
                    subject=f"{jf.path}#L{loc.line}",
                    missing="literal route path",
                    resolution="first arg is not a string literal; "
                    "route path cannot be evidenced"))
                continue
            literal = call.literals[0]
            if _interpolated(literal[2]):
                unknowns.append(UnknownFact(
                    subject=f"{jf.path}#L{loc.line}",
                    missing="literal route path",
                    resolution="template-literal paths are dynamic; "
                    "route cannot be evidenced"))
                continue
            handler = self._handler(jf, call, loc)
            for prefix in prefixes.get(recv, ("",)):
                routes.append(RouteModel(
                    framework=self.framework, service=service,
                    method=verb, path=_norm_js(
                        _join(prefix, _norm(literal[2]))),
                    handler=handler, source_location=loc))

    def _receivers(self, jf: _JsFile) -> set[str]:
        """Variables bound to `express()` / `express.Router()`.

        A var is a receiver iff only whitespace sits between its `=`
        and the factory call; otherwise fall back to the conventional
        `app`/`router` names (attribution already gated the file).
        """
        out = set()
        safe = jf.stripped.safe
        for call in jf.calls:
            if call.name not in ("express", "express.Router"):
                continue
            for name, eq_end in jf.vars.items():
                if eq_end <= call.start and not safe[
                        eq_end:call.start].strip():
                    out.add(name)
        return out or {"app", "router"}

    def _prefixes(
        self,
        jf: _JsFile,
        receivers: set[str],
        unknowns: list[UnknownFact],
    ) -> dict[str, tuple[str, ...]]:
        """`app.use("/p", router)` -> router gets literal prefix `/p`."""
        prefixes: dict[str, tuple[str, ...]] = {}
        for call in jf.calls:
            recv, _, meth = call.name.rpartition(".")
            if meth != "use" or recv not in receivers:
                continue
            lits = call.literals
            if not lits:
                continue
            arg_text = jf.stripped.text[call.open_paren:call.end]
            tail = arg_text.split(lits[0][2], 1)[-1].lstrip(
                ", \t'\"`")
            router_m = re.match(r"([A-Za-z_$][\w$]*)", tail)
            if router_m and router_m.group(1) in receivers:
                var = router_m.group(1)
                prefixes.setdefault(var, ())
                prefixes[var] += (_norm(lits[0][2]),)
            elif tail.startswith(("(", "await", "new ")) or "(" in tail:
                # `app.use("/p", getRouter())` — a call mount whose
                # router binding is not statically visible.
                loc = _loc(jf.path, jf.stripped.text, call.start)
                unknowns.append(UnknownFact(
                    subject=f"{jf.path}#L{loc.line}",
                    missing="static router binding for .use()",
                    resolution="mount target is not a statically known "
                    "router variable"))
        return {k: tuple(sorted(set(v))) or ("",)
                for k, v in prefixes.items()}

    def discover_middleware(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        """`.use(mw)` / `app.use(path, mw)` args as middleware candidates."""
        items: list[SurfaceItem] = []
        for jf in self._parsed(context, files):
            if not self._file_relevant(jf):
                continue
            receivers = self._receivers(jf)
            for call in jf.calls:
                recv, _, meth = call.name.rpartition(".")
                if meth != "use" or recv not in receivers:
                    continue
                args = jf.stripped.safe[
                    call.open_paren + 1:call.end - 1]
                idents = [
                    i for i in re.findall(
                        r"\b([A-Za-z_$][\w$.]*)\b", args)
                    if i not in receivers]
                loc = _loc(jf.path, jf.stripped.text, call.start)
                for ident in idents:
                    items.append(SurfaceItem(
                        label=ident, kind="middleware-candidate",
                        location=loc))
        if not items:
            return unknown_surface("middleware", self.framework)
        return SurfaceResult(surface="middleware", items=tuple(
            sorted(set(items), key=lambda i: (
                i.label, i.location.path, i.location.line or 0))))

    def _handler(
        self, jf: _JsFile, call: _Call, loc: SourceLocation
    ) -> str:
        """First top-level identifier arg after the path literal.

        An arrow/function arg is anonymous — idents *inside* its body
        must never leak into the handler name (no name-inference).
        """
        args = jf.stripped.safe[call.open_paren + 1:call.end - 1]
        depth = 0
        top_args: list[str] = []
        cur: list[str] = []
        for ch in args:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            if ch == "," and depth == 0:
                top_args.append("".join(cur))
                cur = []
            else:
                cur.append(ch)
        top_args.append("".join(cur))
        # Express convention: the handler is the last argument; a bare
        # identifier there is a named handler, anything else is anon.
        last = top_args[-1].strip() if len(top_args) > 1 else ""
        if re.fullmatch(r"[A-Za-z_$][\w$.]*", last):
            return last
        return f"anonymous@{loc.line or 0}"
