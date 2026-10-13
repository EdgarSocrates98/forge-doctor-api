"""FastAPI adapter (§195): pure-`ast` route discovery.

Attribution gate (§101): a file is FastAPI only when *both* markers exist —
a `fastapi` import and a `FastAPI()`/`APIRouter()` instantiation. Text that
merely looks like a decorator never parses into `ast`, so comments and
strings cannot attribute.

Route prefixes compose through `APIRouter(prefix=...)`,
`X.include_router(Y, prefix=...)`, and `FastAPI(root_path=...)` — including
across files, resolved through the project's import graph. Anything dynamic
(non-literal paths, loops registering routes, unresolvable include targets)
is recorded in `RouteScan.unknowns`, never guessed (§101).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field

from forge_doctor_api.analyzers.routes.adapter import (
    AstFrameworkAdapter,
    module_name,
    unknown_surface,
)
from forge_doctor_api.analyzers.routes.model import (
    Attribution,
    ResponseSchemaSource,
    RouteModel,
    RouteParam,
    RouteScan,
    SurfaceItem,
    SurfaceResult,
)
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    SourceLocation,
    UnknownFact,
)

HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)
_PATH_VARS = re.compile(r"\{([^{}/]+)\}")
_DYNAMIC_ROUTERS = ("add_route", "mount", "add_websocket_route")
_SCHEMA_WRAPPERS = ("Security", "Depends")
# Framework-injected handler params — never API contract parameters.
_FRAMEWORK_TYPES = frozenset(
    {
        "Request",
        "Response",
        "BackgroundTasks",
        "WebSocket",
        "WebSocketDisconnect",
        "HTTPConnection",
    }
)


def _ev(path: str, node: ast.AST, summary: str) -> Evidence:
    return Evidence(
        kind=EvidenceKind.STATIC,
        source=path,
        summary=summary,
        line=getattr(node, "lineno", None),
    )


def _loc(path: str, node: ast.AST) -> SourceLocation:
    col = getattr(node, "col_offset", None)
    return SourceLocation(
        path=path,
        line=getattr(node, "lineno", None),
        column=col + 1 if isinstance(col, int) else None,
    )


def _const_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _call_name(func: ast.AST) -> str | None:
    """Dotted name of a call target: `Name` or `a.b.c` attribute chains."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = _call_name(func.value)
        return f"{base}.{func.attr}" if base else func.attr
    return None


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "?"


@dataclass(frozen=True)
class _Obj:
    name: str  # local binding
    kind: str  # "app" | "router"
    prefix: str
    dependencies: tuple[str, ...]
    auth: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Include:
    parent: str  # qualified
    child: str  # qualified
    prefix: str | None  # None = dynamic
    loc: SourceLocation


@dataclass(frozen=True)
class _RawRoute:
    owner: str  # local binding name carrying the decorator/call
    method: str
    path: str | None  # None = dynamic path
    handler: str  # qualified handler name within the module
    auth: tuple[str, ...]
    middleware: tuple[str, ...]
    params: tuple[RouteParam, ...]
    body_params: tuple[str, ...]  # annotated param names; model check is pass 2
    response_schema: str | None
    response_source: ResponseSchemaSource | None
    status_codes: tuple[str, ...]
    loc: SourceLocation


@dataclass
class _Facts:
    path: str
    module: str
    imports: dict[str, str] = field(default_factory=dict)  # local name -> qualified
    objects: dict[str, _Obj] = field(default_factory=dict)
    models: set[str] = field(default_factory=set)  # local pydantic class names
    includes: list[_Include] = field(default_factory=list)
    app_middleware: list[str] = field(default_factory=list)
    routes: list[_RawRoute] = field(default_factory=list)
    dynamic: list[tuple[str, SourceLocation]] = field(default_factory=list)

    def qualify(self, name: str) -> str | None:
        """Local binding -> project-qualified `module.name`, or import target."""
        if name in self.objects:
            return f"{self.module}.{name}"
        return self.imports.get(name)

    def resolve_value(self, node: ast.AST) -> str | None:
        """Best-effort qualified name of a Name/Attribute expression."""
        dotted = _call_name(node)
        if dotted is None:
            return None
        head, _, rest = dotted.partition(".")
        base = self.qualify(head) or self.imports.get(head)
        if base is None:
            return f"{self.module}.{dotted}"
        return f"{base}.{rest}" if rest else base


class _FileScan(ast.NodeVisitor):
    """Collect raw per-file facts; prefix resolution is deferred to pass 2."""

    def __init__(self, facts: _Facts) -> None:
        self.facts = facts
        self.scope: list[str] = []  # enclosing def/class names
        self.dynamic_depth = 0

    # -- imports ----------------------------------------------------------
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = ("." * node.level + (node.module or "")) if node.level else (node.module or "")
        for alias in node.names:
            local = alias.asname or alias.name
            if node.level:
                resolved = self._relative_module(node.level, node.module, alias.name)
            else:
                resolved = f"{base}.{alias.name}"
            self.facts.imports[local] = resolved

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.asname:
                # `import a.b as ab` binds `ab` to module a.b
                self.facts.imports[alias.asname] = alias.name
            else:
                # `import a.b` binds the top-level package `a`
                head = alias.name.split(".", 1)[0]
                self.facts.imports[head] = head

    def _relative_module(self, level: int, module: str | None, name: str) -> str:
        # relative imports resolve against the package of the current module
        package = self.facts.module.split(".")[:-1]
        keep = package[: max(len(package) - (level - 1), 0)]
        qual = ".".join([*keep, module] if module else keep)
        return f"{qual}.{name}" if qual else name

    # -- object construction ----------------------------------------------
    def visit_Assign(self, node: ast.Assign) -> None:
        call = node.value
        if isinstance(call, ast.Call):
            target = _call_name(call.func)
            tail = target.rsplit(".", 1)[-1] if target else ""
            if tail in ("FastAPI", "APIRouter") and self._fastapi_name(target):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.facts.objects[t.id] = self._obj(t.id, tail, call)
        self.generic_visit(node)

    def _fastapi_name(self, dotted: str | None) -> bool:
        if not dotted:
            return False
        head = dotted.split(".", 1)[0]
        resolved = self.facts.imports.get(head, head)
        return resolved == "fastapi" or resolved.startswith("fastapi.")

    def _obj(self, name: str, kind: str, call: ast.Call) -> _Obj:
        if kind == "FastAPI":
            prefix = _const_str(self._kw(call, "root_path")) or ""
        else:
            prefix = _const_str(self._kw(call, "prefix")) or ""
        auth, deps = self._depends_names(self._kw(call, "dependencies"))
        return _Obj(
            name=name,
            kind="app" if kind == "FastAPI" else "router",
            prefix=prefix,
            dependencies=deps,
            auth=auth,
        )

    @staticmethod
    def _kw(call: ast.Call, name: str) -> ast.AST | None:
        for kw in call.keywords:
            if kw.arg == name:
                return kw.value
        return None

    def _depends_names(self, node: ast.AST | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Split `[Depends(x), Security(y)]` into (auth names, dep names)."""
        auth: list[str] = []
        deps: list[str] = []
        if isinstance(node, ast.List | ast.Tuple):
            for item in node.elts:
                if not isinstance(item, ast.Call):
                    continue
                wrapper = (_call_name(item.func) or "").rsplit(".", 1)[-1]
                inner = item.args[0] if item.args else None
                name = (_call_name(inner) or _unparse(inner)) if inner is not None else "?"
                if wrapper == "Security":
                    auth.append(name)
                elif wrapper == "Depends":
                    deps.append(name)
        return tuple(auth), tuple(deps)

    # -- router wiring ------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            owner = _call_name(func.value)
            if func.attr == "include_router" and owner:
                child = node.args[0] if node.args else None
                child_qual = self.facts.resolve_value(child) if child else None
                parent_qual = self.facts.resolve_value(func.value)
                if parent_qual and child_qual:
                    prefix = _const_str(self._kw(node, "prefix"))
                    self.facts.includes.append(
                        _Include(parent_qual, child_qual, prefix, _loc(self.facts.path, node))
                    )
                    if prefix is None:
                        self.facts.dynamic.append(
                            ("dynamic include_router prefix", _loc(self.facts.path, node))
                        )
            elif func.attr == "add_middleware" and owner:
                target = node.args[0] if node.args else None
                name = (_call_name(target) or _unparse(target)) if target is not None else "?"
                self.facts.app_middleware.append(name)
            elif func.attr == "add_api_route" and owner:
                self._explicit_route(owner, node)
            elif func.attr in _DYNAMIC_ROUTERS:
                self.facts.dynamic.append(
                    (f"dynamic route registration via {func.attr}", _loc(self.facts.path, node))
                )
        self.generic_visit(node)

    def _explicit_route(self, owner: str, node: ast.Call) -> None:
        path = _const_str(node.args[0]) if node.args else _const_str(self._kw(node, "path"))
        handler_node = node.args[1] if len(node.args) > 1 else self._kw(node, "endpoint")
        handler = _call_name(handler_node) or _unparse(handler_node) if handler_node else "?"
        methods_node = self._kw(node, "methods")
        methods: list[str] = []
        if isinstance(methods_node, ast.List | ast.Tuple):
            methods = [
                str(m.value).upper() for m in methods_node.elts if isinstance(m, ast.Constant)
            ]
        if not methods:
            methods = ["GET"]
        for method in methods:
            self.facts.routes.append(
                _RawRoute(
                    owner=owner,
                    method=method,
                    path=path,
                    handler=handler,
                    auth=(),
                    middleware=(),
                    params=(),
                    body_params=(),
                    response_schema=None,
                    response_source=None,
                    status_codes=(),
                    loc=_loc(self.facts.path, node),
                )
            )
        if path is None:
            self.facts.dynamic.append(("dynamic add_api_route path", _loc(self.facts.path, node)))

    # -- decorated routes -----------------------------------------------------
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = {_call_name(b) for b in node.bases}
        resolved = {self.facts.imports.get(b.split(".")[0], b.split(".")[0]) for b in bases if b}
        if resolved & {"pydantic", "pydantic.BaseModel"} or any(
            (b or "").endswith("BaseModel") for b in bases
        ):
            self.facts.models.add(node.name)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qual = ".".join([self.facts.module, *self.scope, node.name])
        in_dynamic = self.dynamic_depth > 0
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not (isinstance(func, ast.Attribute) and func.attr in HTTP_METHODS):
                continue
            owner = _call_name(func.value)
            if owner is None:
                continue
            if in_dynamic:
                self.facts.dynamic.append(
                    (f"route declared inside dynamic scope: {qual}", _loc(self.facts.path, node))
                )
                continue
            self.facts.routes.append(self._route(owner, func.attr, decorator, node, qual))
        self.scope.append(node.name)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.For | ast.While | ast.If | ast.With):
                self.dynamic_depth += 1
                self.visit(child)
                self.dynamic_depth -= 1
            else:
                self.visit(child)
        self.scope.pop()

    def _route(
        self,
        owner: str,
        method: str,
        decorator: ast.Call,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        qual: str,
    ) -> _RawRoute:
        path = _const_str(decorator.args[0]) if decorator.args else None
        path_kw = self._kw(decorator, "path")
        if path is None:
            path = _const_str(path_kw)
        if path is None and (decorator.args or path_kw is not None):
            self.facts.dynamic.append(
                (f"dynamic route path on {qual}", _loc(self.facts.path, decorator))
            )
        dec_auth, dec_deps = self._decorator_deps(decorator)
        param_auth, param_deps, params = self._params(node, path)
        auth = tuple(sorted({*dec_auth, *param_auth}))
        deps = tuple(sorted({*dec_deps, *param_deps}))
        response_schema: str | None = None
        source: ResponseSchemaSource | None = None
        rm = self._kw(decorator, "response_model")
        if rm is not None:
            if isinstance(rm, ast.Name | ast.Attribute):
                response_schema = _call_name(rm)
            else:
                response_schema = _unparse(rm)
                self.facts.dynamic.append(
                    (f"dynamic response_model on {qual}", _loc(self.facts.path, decorator))
                )
            source = ResponseSchemaSource.RESPONSE_MODEL
        elif node.returns is not None:
            response_schema = _unparse(node.returns)
            source = ResponseSchemaSource.RETURN_ANNOTATION
        status = self._kw(decorator, "status_code")
        status_codes = (
            (_unparse(status),) if status is not None else ()
        )
        return _RawRoute(
            owner=owner,
            method=method.upper(),
            path=path,
            handler=qual,
            auth=auth,
            middleware=deps,
            params=params,
            body_params=tuple(p.annotation for p in params if p.annotation),
            response_schema=response_schema,
            response_source=source,
            status_codes=status_codes,
            loc=_loc(self.facts.path, decorator),
        )

    def _decorator_deps(self, decorator: ast.Call) -> tuple[list[str], list[str]]:
        auth: list[str] = []
        deps: list[str] = []
        node = self._kw(decorator, "dependencies")
        if isinstance(node, ast.List | ast.Tuple):
            for item in node.elts:
                if isinstance(item, ast.Call):
                    wrapper = (_call_name(item.func) or "").rsplit(".", 1)[-1]
                    inner = item.args[0] if item.args else None
                    name = (
                        (_call_name(inner) or _unparse(inner)) if inner is not None else "?"
                    )
                    if wrapper == "Security":
                        auth.append(name)
                    elif wrapper == "Depends":
                        deps.append(name)
        return auth, deps

    def _params(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, path: str | None
    ) -> tuple[list[str], list[str], tuple[RouteParam, ...]]:
        """Parameter evidence: auth/dependency names plus a `RouteParam` per arg.

        `location_in` comes from wrapper calls (`Path`, `Query`, `Header`,
        `Cookie`, `Body`, `Form`, `File`, `Depends`, `Security`); otherwise the
        path template marks `path` params, and the rest stay `param` until the
        model check in pass 2 promotes known body models to `body`.
        """
        auth: list[str] = []
        deps: list[str] = []
        params: list[RouteParam] = []
        path_vars = frozenset(_PATH_VARS.findall(path or ""))
        pos = [*node.args.posonlyargs, *node.args.args]
        pos_defaults: list[ast.AST | None] = [None] * (len(pos) - len(node.args.defaults)) + list(
            node.args.defaults
        )
        pairs: list[tuple[ast.arg, ast.AST | None]] = list(zip(pos, pos_defaults, strict=True))
        pairs += list(zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True))
        for arg, default in pairs:
            if arg.arg in ("self", "cls"):
                continue
            annotation = (
                _unparse(arg.annotation) if arg.annotation is not None else None
            )
            if annotation is not None:
                head = annotation.split(".", 1)[0]
                resolved = self.facts.imports.get(head, head)
                tail = resolved.rsplit(".", 1)[-1]
                if tail in _FRAMEWORK_TYPES and (
                    resolved.startswith("fastapi") or head in _FRAMEWORK_TYPES
                ):
                    continue  # framework-injected, not an API parameter
            location = "query"  # FastAPI default for scalar params
            required = default is None
            if isinstance(default, ast.Call):
                wrapper = (_call_name(default.func) or "").rsplit(".", 1)[-1]
                inner = default.args[0] if default.args else None
                target = (
                    (_call_name(inner) or _unparse(inner)) if inner is not None else "?"
                )
                if wrapper == "Security":
                    auth.append(target)
                    location = "dependency"
                elif wrapper == "Depends":
                    deps.append(target)
                    location = "dependency"
                elif wrapper in ("Path", "Query", "Header", "Cookie", "Body", "Form", "File"):
                    location = wrapper.lower()
                    has_inner_default = self._kw(default, "default") is not None
                    required = not has_inner_default if wrapper != "Path" else True
            if location == "query" and arg.arg in path_vars:
                location = "path"
                required = True
            params.append(
                RouteParam(
                    name=arg.arg,
                    location_in=location,
                    required=required,
                    annotation=annotation,
                )
            )
        return auth, deps, tuple(params)


class FastApiAdapter(AstFrameworkAdapter):
    """FastAPI route discovery. `service` defaults to the project dir name."""

    name = "fastapi"
    framework = "fastapi"

    def attribute_tree(self, tree: ast.AST, path: str) -> Attribution | None:
        imported = False
        instantiated: ast.AST | None = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("fastapi"):
                imported = True
            elif isinstance(node, ast.Import):
                imported = imported or any(
                    a.name == "fastapi" or a.name.startswith("fastapi.") for a in node.names
                )
            elif isinstance(node, ast.Call):
                name = _call_name(node.func)
                if name and name.rsplit(".", 1)[-1] in ("FastAPI", "APIRouter"):
                    instantiated = node
        if not (imported and instantiated is not None):
            return None
        return Attribution(
            framework=self.framework,
            path=path,
            evidence=(
                Evidence(
                    kind=EvidenceKind.STATIC,
                    source=path,
                    summary="imports fastapi and instantiates FastAPI/APIRouter",
                    line=getattr(instantiated, "lineno", None),
                ),
            ),
        )

    def scan(
        self, context: ProjectContext, service: str, paths: Sequence[str] | None = None
    ) -> RouteScan:
        return self._analyze(context, service, paths)[0]

    def _analyze(
        self, context: ProjectContext, service: str, paths: Sequence[str] | None = None
    ) -> tuple[RouteScan, list[_Facts]]:
        unknowns: list[UnknownFact] = []
        parsed = list(self.parse_files(context, paths, unknowns))

        all_facts: list[_Facts] = []
        global_models: set[str] = set()
        for pf in parsed:
            facts = _Facts(path=pf.path, module=module_name(pf.path))
            scanner = _FileScan(facts)
            # imports first: object attribution depends on them regardless of
            # where the import statement sits in the file
            for node in pf.tree.body:
                if isinstance(node, ast.Import | ast.ImportFrom):
                    scanner.visit(node)
            scanner.visit(pf.tree)
            all_facts.append(facts)
            global_models.update(f"{facts.module}.{m}" for m in facts.models)

        objects: dict[str, _Obj] = {}
        includes: dict[str, list[_Include]] = {}
        for facts in all_facts:
            for name, obj in facts.objects.items():
                objects[f"{facts.module}.{name}"] = obj
            for inc in facts.includes:
                includes.setdefault(inc.child, []).append(inc)

        routes: list[RouteModel] = []
        for facts in all_facts:
            for raw in facts.routes:
                if raw.path is None:
                    continue  # dynamic path already recorded in facts.dynamic
                for prefix in self._prefixes(raw.owner, facts, objects, includes):
                    routes.append(
                        self._route_model(service, facts, raw, prefix, global_models, objects)
                    )
            for message, loc in facts.dynamic:
                unknowns.append(
                    UnknownFact(
                        subject=f"{loc.path}#L{loc.line or '?'}",
                        missing=message,
                        resolution="replace dynamic registration with declarative routing",
                    )
                )
        return (
            RouteScan(
                service=service,
                routes=tuple(sorted(set(routes), key=self._key)),
                attributions=tuple(
                    sorted({p.attribution for p in parsed}, key=lambda a: a.path)
                ),
                unknowns=tuple(
                    sorted(unknowns, key=lambda u: (u.subject, u.missing))
                ),
            ),
            all_facts,
        )

    # -- §39 surfaces -----------------------------------------------------------

    def _surface(
        self,
        surface: str,
        context: ProjectContext,
        files: Sequence[str],
        extract: Callable[[RouteScan, list[_Facts]], list[SurfaceItem]],
    ) -> SurfaceResult:
        scan, facts = self._analyze(context, "", files)
        items = sorted(
            {(i.label, i.kind, i.location.path, i.location.line or 0): i
             for i in extract(scan, facts)}.values(),
            key=lambda i: (i.kind, i.label, i.location.path,
                           i.location.line or 0))
        if not items:
            return unknown_surface(surface, self.framework)
        return SurfaceResult(surface=surface, items=tuple(items))

    def discover_auth(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        def _ex(scan: RouteScan, _: list[_Facts]) -> list[SurfaceItem]:
            return [
                SurfaceItem(
                    label=name, kind="auth-dependency",
                    location=r.source_location)
                for r in scan.routes for name in r.auth
            ]
        return self._surface("auth", context, files, _ex)

    def discover_schemas(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        def _ex(scan: RouteScan, _: list[_Facts]) -> list[SurfaceItem]:
            items = [
                SurfaceItem(
                    label=r.request_schema or "", kind="request-schema",
                    location=r.source_location)
                for r in scan.routes if r.request_schema
            ]
            items += [
                SurfaceItem(
                    label=r.response_schema or "", kind="response-schema",
                    location=r.source_location)
                for r in scan.routes if r.response_schema
            ]
            return items
        return self._surface("schemas", context, files, _ex)

    def discover_dependencies(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        def _ex(scan: RouteScan, _: list[_Facts]) -> list[SurfaceItem]:
            items = [
                SurfaceItem(
                    label=p.annotation or p.name, kind="dependency",
                    location=r.source_location)
                for r in scan.routes for p in r.parameters
                if p.location_in == "dependency"
            ]
            # Depends(...) targets land on RouteModel.middleware —
            # they are injected dependencies, evidenced by name.
            items += [
                SurfaceItem(
                    label=name, kind="depends-target",
                    location=r.source_location)
                for r in scan.routes for name in r.middleware
            ]
            return items
        return self._surface("dependencies", context, files, _ex)

    def discover_middleware(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        def _ex(scan: RouteScan, facts: list[_Facts]) -> list[SurfaceItem]:
            items = [
                SurfaceItem(
                    label=name, kind="route-middleware",
                    location=r.source_location)
                for r in scan.routes for name in r.middleware
            ]
            for f in facts:
                items += [
                    SurfaceItem(
                        label=name, kind="app-middleware",
                        location=SourceLocation(path=f.path))
                    for name in f.app_middleware
                ]
            return items
        return self._surface("middleware", context, files, _ex)

    def discover_error_handlers(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        items = _walk_surface(
            self, context, files, "error-handlers")
        if not items:
            return unknown_surface("error_handlers", self.framework)
        return SurfaceResult(surface="error_handlers", items=items)

    def discover_validation(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        items = _walk_surface(self, context, files, "validation")
        if not items:
            return unknown_surface("validation", self.framework)
        return SurfaceResult(surface="validation", items=items)

    def discover_serialization(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        def _ex(scan: RouteScan, _: list[_Facts]) -> list[SurfaceItem]:
            return [
                SurfaceItem(
                    label=(
                        f"{r.response_schema} "
                        f"({r.response_schema_source.value})"),
                    kind="response-serialization",
                    location=r.source_location)
                for r in scan.routes
                if r.response_schema and r.response_schema_source
            ]
        return self._surface("serialization", context, files, _ex)

    def discover_client_calls(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        items = _walk_surface(self, context, files, "client-calls")
        if not items:
            return unknown_surface("client_calls", self.framework)
        return SurfaceResult(surface="client_calls", items=items)

    # -- pass 2 -------------------------------------------------------------

    def _prefixes(
        self,
        owner: str,
        facts: _Facts,
        objects: dict[str, _Obj],
        includes: dict[str, list[_Include]],
    ) -> tuple[str, ...]:
        """All effective prefixes for a local binding, walking include chains."""
        qual = facts.qualify(owner)
        if qual is None:
            return ("",)
        own = objects.get(qual)
        own_prefix = own.prefix if own else ""
        edges = includes.get(qual, [])
        if not edges:
            return (own_prefix,)
        prefixes: set[str] = set()
        for edge in edges:
            edge_prefix = edge.prefix or ""
            for base in self._chain(edge.parent, objects, includes, {qual}):
                prefixes.add(base + edge_prefix + own_prefix)
        return tuple(sorted(prefixes)) or (own_prefix,)

    def _chain(
        self,
        qual: str,
        objects: dict[str, _Obj],
        includes: dict[str, list[_Include]],
        visiting: set[str],
    ) -> Iterator[str]:
        if qual in visiting:
            return
        visiting.add(qual)
        own = objects.get(qual)
        own_prefix = own.prefix if own else ""
        edges = includes.get(qual, [])
        if not edges:
            yield own_prefix
            return
        for edge in edges:
            for base in self._chain(edge.parent, objects, includes, visiting):
                yield base + (edge.prefix or "") + own_prefix

    @staticmethod
    def _join(prefix: str, path: str) -> str:
        if not prefix:
            return path or "/"
        if not path:
            return prefix
        return prefix.rstrip("/") + "/" + path.lstrip("/")

    def _route_model(
        self,
        service: str,
        facts: _Facts,
        raw: _RawRoute,
        prefix: str,
        global_models: set[str],
        objects: dict[str, _Obj],
    ) -> RouteModel:
        """Pass-2 classification: a param's location is `body` when its
        annotation resolves to a known BaseModel subclass (local or imported),
        `path` when its name appears in the full path template."""
        full_path = self._join(prefix, raw.path or "")
        full_vars = frozenset(_PATH_VARS.findall(full_path))

        def qualify_param(name: str) -> str:
            head, _, rest = name.partition(".")
            base = facts.imports.get(head)
            if base is None:
                return f"{facts.module}.{name}"
            return f"{base}.{rest}" if rest else base

        model_quals = {qualify_param(p) for p in raw.body_params} & global_models
        models = sorted(model_quals)
        params: list[RouteParam] = []
        for param in raw.params:
            location = param.location_in
            required = param.required
            if location == "query":
                if param.name in full_vars:
                    location, required = "path", True
                elif param.annotation and qualify_param(param.annotation) in model_quals:
                    location = "body"
            params.append(
                RouteParam(
                    name=param.name,
                    location_in=location,
                    required=required,
                    annotation=param.annotation,
                )
            )
        owner = objects.get(facts.qualify(raw.owner) or "")
        middleware = tuple(
            sorted({*raw.middleware, *(owner.dependencies if owner else ()), *facts.app_middleware})
        )
        return RouteModel(
            framework=self.framework,
            service=service,
            method=raw.method,
            path=full_path,
            handler=raw.handler,
            auth=tuple(sorted({*raw.auth, *(owner.auth if owner else ())})),
            middleware=middleware,
            parameters=tuple(params),
            request_schema=models[0] if models else None,
            response_schema=raw.response_schema,
            response_schema_source=raw.response_source,
            status_codes=raw.status_codes,
            source_location=raw.loc,
        )

    @staticmethod
    def _key(route: RouteModel) -> tuple[str, str, str, int]:
        loc = route.source_location
        return (route.method, route.path, route.handler, loc.line or 0)


# -- §39 surface walkers (module level; shared by discover_*) ------------------

_HTTP_VERBS = frozenset(
    {"get", "put", "post", "delete", "patch", "head", "options", "request"})
_HTTP_CLIENTS = frozenset({"httpx", "requests", "aiohttp", "urllib3"})


def _walk_surface(
    adapter: AstFrameworkAdapter,
    context: ProjectContext,
    files: Sequence[str],
    surface: str,
) -> tuple[SurfaceItem, ...]:
    """AST pass over attributed files for one non-route surface.

    - `error-handlers`: `@{app}.exception_handler(X)` decorated functions.
    - `validation`: route-handler params with a `Query/Path/Body/Field/`
      `Param` default — binding+constraint evidence.
    - `client-calls`: `httpx|requests|aiohttp.<verb>(` calls where the
      module is imported in that file.
    """
    unknowns: list[UnknownFact] = []
    items: list[SurfaceItem] = []
    for pf in adapter.parse_files(context, files, unknowns):
        client_mods = _imported_client_roots(pf.tree)
        for node in ast.walk(pf.tree):
            if surface == "error-handlers" and isinstance(
                node, ast.FunctionDef | ast.AsyncFunctionDef
            ):
                for dec in node.decorator_list:
                    call = dec if isinstance(dec, ast.Call) else None
                    name = _call_name(call.func if call else dec)
                    if name and name.endswith(".exception_handler"):
                        exc = (
                            _unparse(call.args[0])
                            if call and call.args else "?"
                        )
                        items.append(SurfaceItem(
                            label=f"{exc} -> {node.name}",
                            kind="error-handler",
                            location=SourceLocation(
                                path=pf.path, line=node.lineno)))
            elif surface == "validation" and isinstance(
                node, ast.FunctionDef | ast.AsyncFunctionDef
            ):
                for arg in node.args.args + node.args.kwonlyargs:
                    default = _arg_default(node, arg)
                    if isinstance(default, ast.Call):
                        default_name = _call_name(default.func) or ""
                        head = default_name.rsplit(".", 1)[-1]
                        if head in ("Query", "Path", "Body", "Field",
                                    "Param", "Cookie", "Header"):
                            items.append(SurfaceItem(
                                label=f"{head}({arg.arg})",
                                kind="bound-param",
                                location=SourceLocation(
                                    path=pf.path, line=arg.lineno)))
            elif surface == "error-handlers" and isinstance(
                node, ast.Raise
            ):
                raised = node.exc
                rcall = raised if isinstance(raised, ast.Call) else None
                raise_head = _call_name(rcall.func) if rcall else (
                    _call_name(raised) if raised is not None else None)
                if raise_head and raise_head.endswith("HTTPException"):
                    status = ""
                    if rcall:
                        status = next(
                            (_unparse(kw.value) for kw in rcall.keywords
                             if kw.arg == "status_code"),
                            _unparse(rcall.args[0]) if rcall.args else "")
                    items.append(SurfaceItem(
                        label=(f"raise HTTPException({status})" if status
                               else "raise HTTPException"),
                        kind="http-error",
                        location=SourceLocation(
                            path=pf.path, line=node.lineno)))
            elif surface == "client-calls" and client_mods and isinstance(
                node, ast.Call
            ):
                name = _call_name(node.func) or ""
                head, _, verb = name.partition(".")
                if head in client_mods and verb in _HTTP_VERBS:
                    items.append(SurfaceItem(
                        label=name, kind="http-client-call",
                        location=SourceLocation(
                            path=pf.path, line=node.lineno)))
    return tuple(sorted(
        items, key=lambda i: (i.kind, i.label, i.location.path,
                              i.location.line or 0)))


def _imported_client_roots(tree: ast.Module) -> frozenset[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]]
        roots.update(n for n in names if n in _HTTP_CLIENTS)
    return frozenset(roots)


def _arg_default(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, arg: ast.arg
) -> ast.AST | None:
    if arg in fn.args.args:
        idx = fn.args.args.index(arg)
        offset = len(fn.args.args) - len(fn.args.defaults)
        if idx >= offset:
            return fn.args.defaults[idx - offset]
    elif arg in fn.args.kwonlyargs:
        idx = fn.args.kwonlyargs.index(arg)
        return fn.args.kw_defaults[idx]
    return None
