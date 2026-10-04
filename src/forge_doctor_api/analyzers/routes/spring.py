"""Spring Boot adapter (§42-§46): zero-dependency static scanner.

Java is parsed with `textscan.strip_source` — comments and string
interiors are blanked, so `@GetMapping` text inside a comment or a
string literal can never produce a route, while the literal argument
inside a real annotation is still resolvable.

Extraction is an annotation state machine:

1. every `@Name(...)` is recorded with its resolved literal args;
2. `class/record` declarations and `Type method(...)` signatures are
   located on the stripped text;
3. an annotation attaches to the next declaration after it —
   class-level vs method-level falls out of position alone.

Anything non-literal (constant refs, concatenation, SpEL, conditional
registration via `@ConditionalOn*`) is recorded as an `UnknownFact` —
never guessed (§48-§49).
"""

from __future__ import annotations

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
    RouteParam,
    RouteScan,
    SurfaceItem,
    SurfaceResult,
)
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

_METHOD_ANNOTATIONS: dict[str, frozenset[str]] = {
    "GetMapping": frozenset({"GET"}),
    "PostMapping": frozenset({"POST"}),
    "PutMapping": frozenset({"PUT"}),
    "DeleteMapping": frozenset({"DELETE"}),
    "PatchMapping": frozenset({"PATCH"}),
    "RequestMapping": frozenset(),  # resolved from method= args
}
_CLASS_ANNOTATIONS = frozenset(
    {"RestController", "Controller", "RequestMapping"})
_CONDITIONAL = re.compile(r"@Conditional\w*")
_SPRING_IMPORT = "org.springframework"

_ANNOTATION_RE = re.compile(r"@([A-Za-z_]\w*)(?:\s*\()?", re.ASCII)
_CLASS_RE = re.compile(
    r"(?:^|[\s{;])(?:public\s+|abstract\s+|final\s+|static\s+)*"
    r"(?:class|record)\s+([A-Za-z_]\w*)")
_METHOD_RE = re.compile(
    r"\b(?:public|protected|private)\s+"
    r"(?:static\s+|final\s+|synchronized\s+|abstract\s+)*"
    r"[A-Za-z_][\w<>\[\],.\s?]*?\s([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*"
    r"(?:throws\s+[\w.,\s]+)?\{")
_REQMETHOD_RE = re.compile(r"RequestMethod\.([A-Z]+)")
_NAMED_ARG_RE = re.compile(r"(?:value|path|name)\s*=")
_PARAM_ANNOTATION_RE = re.compile(
    r"@(PathVariable|RequestParam|RequestHeader|RequestBody|"
    r"ModelAttribute|Valid|Validated)\b")


@dataclass(frozen=True)
class _Annotation:
    name: str
    start: int
    end: int
    args_text: str  # original-text args (literals resolved by caller)
    literals: tuple[str, ...]


@dataclass
class _JavaFile:
    path: str
    stripped: StrippedSource
    annotations: list[_Annotation] = field(default_factory=list)
    classes: list[tuple[int, str]] = field(default_factory=list)
    methods: list[tuple[int, int, str, str, int]] = field(
        default_factory=list)  # (start, end, name, params, params_pos)


def _balanced_end(safe: str, start: int) -> int:
    """End offset of a `(`-opened balanced region; len(safe) if open."""
    depth = 0
    for k in range(start, len(safe)):
        ch = safe[k]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return k + 1
    return len(safe)


def _parse_java(path: str, text: str) -> _JavaFile:
    stripped = strip_source(text)
    jf = _JavaFile(path=path, stripped=stripped)
    for m in _ANNOTATION_RE.finditer(stripped.safe):
        name = m.group(1)
        start, end = m.start(), m.end()
        args = ""
        if stripped.safe[m.end() - 1] == "(":
            end = _balanced_end(stripped.safe, m.end() - 1)
            args = stripped.text[m.end():end - 1]
        lits = tuple(
            lit[2] for lit in stripped.literals
            if m.end() <= lit[0] < end)
        jf.annotations.append(
            _Annotation(name, start, end, args, lits))
    for m in _CLASS_RE.finditer(stripped.safe):
        jf.classes.append((m.start(), m.group(1)))
    for m in _METHOD_RE.finditer(stripped.safe):
        jf.methods.append(
            (m.start(), m.end(), m.group(1), m.group(2), m.start(2)))
    return jf


def _attached(
    anns: Sequence[_Annotation], start: int, prev_end: int
) -> list[_Annotation]:
    """Annotations in (prev_end, start) — the pending block."""
    return [a for a in anns if prev_end < a.start < start]


def _loc(path: str, text: str, pos: int) -> SourceLocation:
    return SourceLocation(path=path, line=line_of(text, pos))


def _paths(ann: _Annotation) -> tuple[str, ...]:
    """Literal paths collected from the annotation args."""
    return tuple(sorted(set(ann.literals)))


def _norm(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


def _join(prefix: str, sub: str) -> str:
    joined = f"{prefix.rstrip('/')}/{sub.lstrip('/')}"
    return joined.rstrip("/") or "/"


class SpringBootAdapter(FrameworkAdapter):
    """Spring Boot static discovery (Java). No exec, no name-inference."""

    name = "spring"
    framework = "spring"
    file_pattern = "**/*.java"

    def _files(
        self, context: ProjectContext, files: Sequence[str] | None
    ) -> list[str]:
        src = list(files) if files is not None else list(
            context.iter_files(self.file_pattern))
        return sorted(
            f for f in src
            if f.endswith(".java") and not is_skippable(f))

    def _parsed(
        self, context: ProjectContext, files: Sequence[str] | None
    ) -> list[_JavaFile]:
        parsed: list[_JavaFile] = []
        for rel in self._files(context, files):
            try:
                parsed.append(_parse_java(rel, context.read_text(rel)))
            except Exception:
                continue
        return parsed

    def detect(
        self, context: ProjectContext, files: Sequence[str]
    ) -> bool:
        names = {f.rsplit("/", 1)[-1] for f in files}
        manifests = names & {
            "pom.xml", "build.gradle", "build.gradle.kts"}
        for f in sorted(files):
            base = f.rsplit("/", 1)[-1]
            try:
                if (base in manifests or f.endswith(".java")) and (
                        _SPRING_IMPORT in context.read_text(f)):
                    return True
            except Exception:
                continue
        return False

    def attribute(
        self, context: ProjectContext, files: Sequence[str]
    ) -> tuple[Attribution, ...]:
        attrs: list[Attribution] = []
        for jf in self._parsed(context, files):
            has_import = _SPRING_IMPORT in jf.stripped.safe
            marker = next(
                (a for a in jf.annotations
                 if a.name in _CLASS_ANNOTATIONS | frozenset(
                     _METHOD_ANNOTATIONS)),
                None)
            if has_import and marker is not None:
                attrs.append(Attribution(
                    framework=self.framework, path=jf.path,
                    evidence=(Evidence(
                        kind=EvidenceKind.STATIC, source=jf.path,
                        summary="imports org.springframework and "
                        "declares a controller/mapping annotation",
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
            attributed = self._routes_file(jf, service, routes, unknowns)
            if attributed is not None:
                attributions.append(attributed)
        return RouteScan(
            service=service,
            routes=tuple(sorted(
                routes, key=lambda r: (r.method, r.path, r.handler))),
            attributions=tuple(attributions),
            unknowns=tuple(sorted(
                unknowns, key=lambda u: (u.subject, u.missing))),
        )

    def _routes_file(
        self,
        jf: _JavaFile,
        service: str,
        routes: list[RouteModel],
        unknowns: list[UnknownFact],
    ) -> Attribution | None:
        if _SPRING_IMPORT not in jf.stripped.safe:
            return None
        text = jf.stripped.text
        attr: Attribution | None = None
        decls = sorted(
            [(c[0], "class", c[1], "", 0) for c in jf.classes]
            + [(m[0], "method", m[2], m[3], m[4]) for m in jf.methods])
        prev_end = 0
        class_name = ""
        class_prefix = ""
        class_conditional = False
        for start, kind, name, params, params_pos in decls:
            anns = _attached(jf.annotations, start, prev_end)
            if kind == "class":
                class_name = name
                class_prefix = self._class_prefix(anns)
                class_conditional = any(
                    a.name.startswith("Conditional") for a in anns)
                marker = next(
                    (a for a in anns if a.name in _CLASS_ANNOTATIONS),
                    None)
                if marker is not None:
                    attr = Attribution(
                        framework=self.framework, path=jf.path,
                        evidence=(Evidence(
                            kind=EvidenceKind.STATIC, source=jf.path,
                            summary=f"@{marker.name} on class {name}",
                            line=line_of(text, marker.start)),))
            else:
                self._method_routes(
                    jf, service, class_name, class_prefix,
                    class_conditional, name,
                    params, params_pos, anns, start, routes, unknowns)
            prev_end = start
        return attr

    def _class_prefix(self, anns: Sequence[_Annotation]) -> str:
        for a in anns:
            if a.name == "RequestMapping" and a.literals:
                return _norm(a.literals[0])
        return ""

    def _method_routes(
        self,
        jf: _JavaFile,
        service: str,
        class_name: str,
        class_prefix: str,
        class_conditional: bool,
        method: str,
        params_text: str,
        params_pos: int,
        anns: Sequence[_Annotation],
        pos: int,
        routes: list[RouteModel],
        unknowns: list[UnknownFact],
    ) -> None:
        text = jf.stripped.text
        loc = _loc(jf.path, text, pos)
        conditional = class_conditional or any(
            a.name.startswith("Conditional") for a in anns)
        for ann in anns:
            if ann.name not in _METHOD_ANNOTATIONS:
                continue
            methods = set(_METHOD_ANNOTATIONS[ann.name])
            if ann.name == "RequestMapping":
                methods = set(_REQMETHOD_RE.findall(ann.args_text))
                if not methods:
                    unknowns.append(UnknownFact(
                        subject=f"{jf.path}#L{loc.line}",
                        missing="HTTP method on @RequestMapping",
                        resolution="declare method=RequestMethod.X or "
                        "use the typed mapping annotations"))
                    continue
            paths = _paths(ann)
            if not paths:
                # A bare @GetMapping is legal — it inherits the class
                # prefix (or "/"); only a *dynamic* arg is unknown.
                has_args = ann.args_text.strip()
                if has_args:
                    unknowns.append(UnknownFact(
                        subject=f"{jf.path}#L{loc.line}",
                        missing="literal route path",
                        resolution="annotation arg is not a string "
                        "literal; route path cannot be evidenced"))
                    continue
                paths = ("",)
            for sub in paths:
                full = _join(class_prefix, sub) if sub else (
                    class_prefix or "/")
                for http in sorted(methods):
                    routes.append(RouteModel(
                        framework=self.framework, service=service,
                        method=http, path=full,
                        handler=f"{class_name}.{method}",
                        parameters=self._params(
                            params_text, params_pos, jf, loc),
                        source_location=loc))
                if conditional:
                    unknowns.append(UnknownFact(
                        subject=f"{jf.path}#L{loc.line}",
                        missing="unconditional route registration",
                        resolution="@Conditional* gates this handler; "
                        "activation depends on runtime properties"))

    def _params(
        self, params_text: str, params_pos: int,
        jf: _JavaFile, loc: SourceLocation,
    ) -> tuple[RouteParam, ...]:
        out: list[RouteParam] = []
        for m in _PARAM_ANNOTATION_RE.finditer(params_text):
            kind = m.group(1)
            where = {
                "PathVariable": "path", "RequestParam": "query",
                "RequestHeader": "header", "RequestBody": "body",
            }.get(kind)
            if where is None:
                continue
            tail = params_text[m.end():]
            # literal alias first: @RequestParam("q") String q -> "q";
            # literal must sit inside this annotation's args window.
            abs_end = params_pos + m.end()
            window_end = abs_end + 80
            lit = next(
                (v for s, _, v in jf.stripped.literals
                 if abs_end <= s < window_end
                 and not tail[: s - abs_end].rstrip(" \t").endswith(",")),
                None)
            if lit is None:
                seg = tail.split(",", 1)[0]
                seg = seg.split(")", 1)[0]
                name_m = re.search(
                    r"[\w<>\[\].]+?\s+([A-Za-z_]\w*)\s*$", seg.strip())
                name = name_m.group(1) if name_m else "?"
            else:
                name = lit
            out.append(RouteParam(
                name=name, location_in=where,
                required=kind != "RequestParam"))
        return tuple(out)

    # -- §39 surfaces ---------------------------------------------------------

    def _surface_items(
        self,
        context: ProjectContext,
        files: Sequence[str],
        kinds: dict[str, str],
    ) -> tuple[SurfaceItem, ...]:
        """Project annotations matching `kinds` -> kind labels."""
        items: list[SurfaceItem] = []
        for jf in self._parsed(context, files):
            if _SPRING_IMPORT not in jf.stripped.safe:
                continue
            for ann in jf.annotations:
                kind = kinds.get(ann.name)
                if kind is None:
                    continue
                lit = ann.literals[0] if ann.literals else ""
                items.append(SurfaceItem(
                    label=f"@{ann.name}({lit})" if lit
                    else f"@{ann.name}",
                    kind=kind,
                    location=_loc(jf.path, jf.stripped.text, ann.start)))
        return tuple(sorted(set(items), key=lambda i: (
            i.kind, i.label, i.location.path, i.location.line or 0)))

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
            "PreAuthorize": "auth-expression",
            "PostAuthorize": "auth-expression",
            "Secured": "auth-roles",
            "RolesAllowed": "auth-roles",
        })

    def discover_schemas(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        items = self._surface_items(context, files, {
            "RequestBody": "request-schema"})
        if not items:
            return unknown_surface("schemas", self.framework)
        return SurfaceResult(surface="schemas", items=items)

    def discover_dependencies(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        return self._surface("dependencies", context, files, {
            "Autowired": "injection", "Inject": "injection",
            "Bean": "bean-factory", "Qualifier": "qualifier",
        })

    def discover_middleware(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        return self._surface("middleware", context, files, {
            "Component": "component-candidate",
            "Order": "ordered-component",
            "WebMvcConfigurer": "mvc-configurer",
        })

    def discover_error_handlers(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        return self._surface("error_handlers", context, files, {
            "ExceptionHandler": "error-handler",
            "ControllerAdvice": "advice-class",
            "RestControllerAdvice": "advice-class",
        })

    def discover_validation(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        return self._surface("validation", context, files, {
            "Valid": "validation-marker",
            "Validated": "validation-marker",
            "NotNull": "constraint", "Size": "constraint",
            "Min": "constraint", "Max": "constraint",
            "Pattern": "constraint",
        })

    def discover_serialization(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        return self._surface("serialization", context, files, {
            "JsonProperty": "json-mapping",
            "JsonIgnore": "json-mapping",
            "ResponseBody": "body-serialization",
        })

    def discover_client_calls(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        items: list[SurfaceItem] = []
        for jf in self._parsed(context, files):
            safe = jf.stripped.safe
            for m in re.finditer(
                r"\b(RestTemplate|WebClient|RestClient|FeignClient)"
                r"(?:\.[A-Za-z_]\w*)?\s*\(", safe):
                items.append(SurfaceItem(
                    label=m.group(1), kind="http-client-call",
                    location=_loc(jf.path, jf.stripped.text, m.start())))
            if "@FeignClient" in safe:
                items.append(SurfaceItem(
                    label="@FeignClient", kind="http-client-contract",
                    location=_loc(
                        jf.path, jf.stripped.text,
                        safe.index("@FeignClient"))))
        if not items:
            return unknown_surface("client_calls", self.framework)
        return SurfaceResult(surface="client_calls", items=tuple(
            sorted(items, key=lambda i: (
                i.label, i.location.path, i.location.line or 0))))
