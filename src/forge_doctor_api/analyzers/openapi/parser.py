"""Build an `OpenApiProjectModel` from project files (§10, §142).

Pipeline:

1. Load candidate files through `ProjectContext` (hermetic, §203).
2. Gate each file on the strong `openapi` marker (§101).
3. Walk every loaded document once (iteratively) to collect `$ref` sites and
   `x-*` extensions; load cross-file targets lazily as FRAGMENT documents.
   URL refs are recorded as `UnresolvedExternalRef` and never fetched.
4. Detect reference cycles over the reference graph (SCC) and record them.
5. Extract §10.1 elements from supported root documents, following `$ref`
   chains with a visited set so alias loops terminate.

Model only: no findings are emitted here.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_left
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from posixpath import splitext
from typing import Any, TypeVar

from forge_doctor_api.analyzers.openapi.detection import detect_openapi
from forge_doctor_api.analyzers.openapi.identity import operation_identity
from forge_doctor_api.analyzers.openapi.knowledge import HTTP_METHODS_3_2
from forge_doctor_api.analyzers.openapi.loader import (
    Locations,
    escape_pointer_token,
    load_document,
)
from forge_doctor_api.analyzers.openapi.model import (
    OPENAPI_MODEL_SCHEMA_VERSION,
    CycleKind,
    DocumentStatus,
    IssueCode,
    OpenApiCallback,
    OpenApiDocument,
    OpenApiExtension,
    OpenApiExternalDocs,
    OpenApiIssue,
    OpenApiOperation,
    OpenApiParameter,
    OpenApiPathItem,
    OpenApiProjectModel,
    OpenApiReference,
    OpenApiRequestBody,
    OpenApiResponse,
    OpenApiSchema,
    OpenApiSchemeUse,
    OpenApiSecurityRequirement,
    OpenApiSecurityScheme,
    OpenApiServer,
    OpenApiTag,
    OpenApiWebhook,
    OperationSource,
    ReferenceCycle,
    RefStatus,
    UnresolvedExternalRef,
)
from forge_doctor_api.analyzers.openapi.refs import (
    classify,
    is_missing,
    lookup,
    strongly_connected,
    within,
)
from forge_doctor_api.core.context import ContextError, ProjectContext
from forge_doctor_api.core.models import Model, SourceLocation

CANDIDATE_SUFFIXES = (".yaml", ".yml", ".json")
_SKIP_DIRS = frozenset({"node_modules", "__pycache__", "site-packages"})
_MARKER = re.compile(r"""(?:^|[{,])\s*["']?openapi["']?\s*:""", re.MULTILINE)

# Keys whose values are user data, not OpenAPI structure: no refs/extensions inside.
_DATA_KEYS = frozenset({"example", "default", "enum", "const"})
# Example Object payloads (`examples/{name}/value`; 3.2 adds dataValue/serializedValue).
_EXAMPLE_VALUE_KEYS = frozenset({"value", "dataValue", "serializedValue"})
# Mappings whose keys are names (property names, media types, scheme names...),
# so a key like `$ref` or `x-foo` there is a name, not a keyword.
_NAME_MAPS = frozenset(
    {
        "properties",
        "patternProperties",
        "dependentSchemas",
        "$defs",
        "definitions",
        "content",
        "headers",
        "encoding",
        "links",
        "examples",
        "variables",
        "scopes",
        "mapping",
        "security",
        "webhooks",
        "pathItems",
        "mediaTypes",
    }
)
_DYNAMIC_KEYWORDS = ("$dynamicRef", "$recursiveRef")
_MAX_REF_HOPS = 64

T = TypeVar("T", bound=Model)


@dataclass
class _Doc:
    path: str
    fmt: str
    status: DocumentStatus
    value: Any = None
    locations: Locations = field(default_factory=dict)
    version: str | None = None
    family: str | None = None

    @property
    def usable(self) -> bool:
        return self.status in (DocumentStatus.PARSED, DocumentStatus.FRAGMENT)


@dataclass(frozen=True)
class _RefSite:
    path: str
    pointer: str  # the object holding the keyword
    keyword: str
    ref: Any


def _fmt(path: str) -> str:
    return "json" if splitext(path)[1].lower() == ".json" else "yaml"


def _skipped(path: str) -> bool:
    parts = path.split("/")[:-1]
    return any(part.startswith(".") or part in _SKIP_DIRS for part in parts)


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _bool(value: Any) -> bool:
    return value is True


def _content_types(node: Any) -> tuple[str, ...]:
    content = node.get("content") if isinstance(node, dict) else None
    return tuple(sorted(str(k) for k in content)) if isinstance(content, dict) else ()


def _child(pointer: str, token: str) -> str:
    return f"{pointer}/{escape_pointer_token(token)}"


def _unique_sorted(items: Iterable[T]) -> tuple[T, ...]:
    """Drop exact duplicates; order by (path, pointer, canonical content)."""
    keyed: dict[str, tuple[tuple[str, str, str], T]] = {}
    for item in items:
        canonical = json.dumps(item._encode_fields(), sort_keys=True, ensure_ascii=False)
        location = getattr(item, "location", None)
        path = location.path if isinstance(location, SourceLocation) else ""
        keyed[canonical] = ((path, str(getattr(item, "pointer", "")), canonical), item)
    return tuple(item for _, item in sorted(keyed.values(), key=lambda pair: pair[0]))


class _Builder:
    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.docs: dict[str, _Doc] = {}
        self.issues: list[OpenApiIssue] = []
        self.sites: list[_RefSite] = []
        self.targets: dict[tuple[str, int], tuple[str | None, str | None, RefStatus]] = {}
        self.out: dict[str, list[Any]] = {}
        self.walked: set[str] = set()
        self.visited_items: set[tuple[str, str, str, str]] = set()

    # -- locations & issues -------------------------------------------------

    def loc(self, path: str, pointer: str = "") -> SourceLocation:
        doc = self.docs.get(path)
        locations = doc.locations if doc is not None else {}
        probe = pointer
        while True:
            if probe in locations:
                line, column = locations[probe]
                return SourceLocation(path=path, line=line, column=column)
            if not probe:
                return SourceLocation(path=path)
            probe = probe.rsplit("/", 1)[0]

    def issue(
        self,
        code: IssueCode,
        message: str,
        path: str,
        pointer: str = "",
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        if line is not None:
            location = SourceLocation(path=path, line=line, column=column)
        else:
            location = self.loc(path, pointer)
        self.issues.append(OpenApiIssue(code=code, message=message, location=location))

    def add(self, bucket: str, item: Model) -> None:
        self.out.setdefault(bucket, []).append(item)

    # -- loading ------------------------------------------------------------

    def load(self, path: str, *, root: bool, explicit: bool) -> _Doc | None:
        if path in self.docs:
            return self.docs[path]
        fmt = _fmt(path)
        try:
            text = self.context.read_text(path)
        except (ContextError, OSError, UnicodeDecodeError) as exc:
            reason = exc.reason if isinstance(exc, UnicodeDecodeError) else type(exc).__name__
            doc = _Doc(path, fmt, DocumentStatus.UNREADABLE)
            self.docs[path] = doc
            self.issue(IssueCode.UNREADABLE, f"cannot read {path}: {reason}", path)
            return doc
        loaded = load_document(text, fmt)
        if not loaded.ok:
            if root and not explicit and not _MARKER.search(text):
                return None  # discovery: malformed file with no OpenAPI marker is not ours
            doc = _Doc(path, fmt, DocumentStatus.MALFORMED)
            self.docs[path] = doc
        else:
            if root:
                detection = detect_openapi(loaded.value)
                if detection.status is DocumentStatus.NOT_OPENAPI and not explicit:
                    return None
                status = detection.status
            else:
                detection = None
                status = DocumentStatus.FRAGMENT
            doc = _Doc(
                path,
                fmt,
                status,
                value=loaded.value,
                locations=loaded.locations,
                version=detection.version if detection else None,
                family=detection.family if detection else None,
            )
            self.docs[path] = doc
            if detection is not None and detection.status is not DocumentStatus.PARSED:
                has_marker = isinstance(loaded.value, dict) and "openapi" in loaded.value
                self.issue(
                    IssueCode(detection.status.value),
                    detection.reason,
                    path,
                    "/openapi" if has_marker else "",
                )
        for problem in loaded.issues:
            self.issue(
                IssueCode(problem.code), problem.message, path, "", problem.line, problem.column
            )
        return doc

    # -- traversal ----------------------------------------------------------

    def walk(self, doc: _Doc) -> None:
        """Collect `$ref` sites and `x-*` extensions in one iterative pass."""
        # Frame: (value, pointer, key of this value in its parent, is_name_map, parent_key)
        stack: list[tuple[Any, str, str | None, bool, str | None]] = [
            (doc.value, "", None, False, None)
        ]
        while stack:
            value, pointer, key, name_map, parent_key = stack.pop()
            if isinstance(value, list):
                if key in ("examples",):
                    continue  # JSON Schema `examples` array: data
                for index in reversed(range(len(value))):
                    item = value[index]
                    item_is_name_map = key == "security" and isinstance(item, dict)
                    stack.append((item, _child(pointer, str(index)), None, item_is_name_map, key))
                continue
            if not isinstance(value, dict):
                continue
            children: list[tuple[Any, str, str | None, bool, str | None]] = []
            for child_key in value:
                child_value = value[child_key]
                child_pointer = _child(pointer, child_key)
                if not name_map:
                    if child_key == "$ref":
                        self.sites.append(_RefSite(doc.path, pointer, "$ref", child_value))
                        continue
                    if child_key in _DYNAMIC_KEYWORDS:
                        self.sites.append(_RefSite(doc.path, pointer, child_key, child_value))
                        continue
                    if child_key.startswith("x-"):
                        self.add(
                            "extensions",
                            OpenApiExtension(
                                location=self.loc(doc.path, child_pointer),
                                pointer=child_pointer,
                                owner_pointer=pointer,
                                name=child_key,
                                value=child_value,
                            ),
                        )
                        continue
                    if child_key in _DATA_KEYS:
                        continue
                    if parent_key == "examples" and child_key in _EXAMPLE_VALUE_KEYS:
                        continue
                child_name_map = (
                    not name_map
                    and isinstance(child_value, dict)
                    and (child_key in _NAME_MAPS or pointer == "/components")
                )
                children.append((child_value, child_pointer, child_key, child_name_map, key))
            stack.extend(reversed(children))

    def resolve_sites(self, start: int) -> None:
        """Classify ref sites from `start` on, loading cross-file targets lazily."""
        index = start
        while index < len(self.sites):
            site = self.sites[index]
            doc = self.docs[site.path]
            location = self.loc(site.path, _child(site.pointer, site.keyword))
            if site.keyword in _DYNAMIC_KEYWORDS:
                self.targets[(site.path, index)] = (None, None, RefStatus.DYNAMIC)
                self.add(
                    "references",
                    OpenApiReference(
                        location=location,
                        pointer=site.pointer,
                        ref=str(site.ref),
                        status=RefStatus.DYNAMIC,
                        keyword=site.keyword,
                    ),
                )
                index += 1
                continue
            target = classify(site.ref, doc.path)
            status = target.status
            if status is RefStatus.INVALID:
                self.issue(
                    IssueCode.INVALID_REF,
                    f"invalid $ref {site.ref!r}: {target.reason}",
                    site.path,
                    _child(site.pointer, "$ref"),
                )
            elif status in (RefStatus.EXTERNAL, RefStatus.OUTSIDE_ROOT):
                self.add(
                    "unresolved",
                    UnresolvedExternalRef(
                        location=location, pointer=site.pointer, ref=str(site.ref), reason=status
                    ),
                )
            elif target.path is not None and target.pointer is not None:
                target_doc = self.load(target.path, root=False, explicit=True)
                fresh = target_doc is not None and target_doc.path not in self.walked
                if target_doc is not None and target_doc.usable and fresh:
                    self.walked.add(target_doc.path)
                    self.walk(target_doc)
                found = (
                    target_doc is not None
                    and target_doc.usable
                    and not is_missing(lookup(target_doc.value, target.pointer))
                )
                if not found:
                    status = RefStatus.MISSING
                    self.issue(
                        IssueCode.MISSING_REF_TARGET,
                        f"$ref target not found: {site.ref!r}",
                        site.path,
                        _child(site.pointer, "$ref"),
                    )
            self.targets[(site.path, index)] = (target.path, target.pointer, status)
            self.add(
                "references",
                OpenApiReference(
                    location=location,
                    pointer=site.pointer,
                    ref=str(site.ref),
                    status=status,
                    keyword=site.keyword,
                    target_path=target.path if status is RefStatus.RESOLVED else None,
                    target_pointer=target.pointer if status is RefStatus.RESOLVED else None,
                ),
            )
            index += 1

    # -- cycles -------------------------------------------------------------

    def detect_cycles(self) -> None:
        resolved: list[tuple[_RefSite, str]] = []
        for index, site in enumerate(self.sites):
            target_path, target_pointer, status = self.targets[(site.path, index)]
            if status is RefStatus.RESOLVED and target_path is not None:
                resolved.append((site, f"{target_path}#{target_pointer}"))
        nodes = sorted({node for _, node in resolved})
        # Per document, ref sites sorted by pointer: sites inside a target form a
        # contiguous range ("p" itself, then "p/..." up to "p0"), found by bisection.
        by_doc: dict[str, list[tuple[str, int]]] = {}
        for position, (site, _) in enumerate(resolved):
            by_doc.setdefault(site.path, []).append((site.pointer, position))
        for entries in by_doc.values():
            entries.sort()
        edges: dict[str, list[str]] = {}
        contributors: dict[tuple[str, str], list[_RefSite]] = {}
        for node in nodes:
            node_path, _, node_pointer = node.partition("#")
            entries = by_doc.get(node_path, [])
            if node_pointer:
                lo = bisect_left(entries, (node_pointer, -1))
                hi = bisect_left(entries, (node_pointer + "0", -1))
            else:
                lo, hi = 0, len(entries)
            for site_pointer, position in entries[lo:hi]:
                if not within(site_pointer, node_pointer):
                    continue
                site, target = resolved[position]
                edges.setdefault(node, []).append(target)
                contributors.setdefault((node, target), []).append(site)
        for component in strongly_connected(nodes, edges):
            members = set(component)
            closing = sorted(
                (site.path, site.pointer)
                for (source, target), sites in contributors.items()
                if source in members and target in members
                for site in sites
            )
            path, pointer = closing[0]
            alias = all(self.is_pure_ref(member) for member in component)
            self.add(
                "cycles",
                ReferenceCycle(
                    kind=CycleKind.ALIAS if alias else CycleKind.RECURSIVE,
                    members=tuple(component),
                    location=self.loc(path, _child(pointer, "$ref")),
                    pointer=pointer,
                ),
            )

    def is_pure_ref(self, node: str) -> bool:
        path, _, pointer = node.partition("#")
        value = lookup(self.docs[path].value, pointer)
        return isinstance(value, dict) and "$ref" in value

    # -- dereferencing ------------------------------------------------------

    def deref(self, path: str, pointer: str, value: Any) -> tuple[str, str, Any] | None:
        """Follow a `$ref` chain to a concrete object; None on loop/miss/external."""
        seen: set[tuple[str, str]] = set()
        for _ in range(_MAX_REF_HOPS):
            if not isinstance(value, dict) or "$ref" not in value:
                return path, pointer, value
            if (path, pointer) in seen:
                return None
            seen.add((path, pointer))
            target = classify(value["$ref"], path)
            if target.status is not RefStatus.RESOLVED or target.path is None:
                return None
            doc = self.docs.get(target.path)
            if doc is None or not doc.usable or target.pointer is None:
                return None
            found = lookup(doc.value, target.pointer)
            if is_missing(found):
                return None
            path, pointer, value = target.path, target.pointer, found
        return None

    # -- extraction ---------------------------------------------------------

    def extract(self, doc: _Doc) -> None:
        root = doc.value
        path = doc.path
        info = root.get("info") if isinstance(root.get("info"), dict) else {}
        self.add(
            "documents",
            OpenApiDocument(
                location=self.loc(path),
                format=doc.fmt,
                status=doc.status,
                openapi_version=doc.version,
                version_family=doc.family,
                title=_str(info.get("title")),
                api_version=_str(info.get("version")),
                json_schema_dialect=_str(root.get("jsonSchemaDialect")),
                self_uri=_str(root.get("$self")),
            ),
        )
        self.servers(path, "", root)
        self.security(path, "", "", root)
        self.external_docs(path, "", root)
        tags = root.get("tags")
        if isinstance(tags, list):
            for index, tag in enumerate(tags):
                pointer = f"/tags/{index}"
                if isinstance(tag, dict) and isinstance(tag.get("name"), str):
                    self.add(
                        "tags",
                        OpenApiTag(
                            location=self.loc(path, pointer),
                            pointer=pointer,
                            name=tag["name"],
                            description=_str(tag.get("description")),
                            parent=_str(tag.get("parent")),
                        ),
                    )
                    self.external_docs(path, pointer, tag)
        self.components(path, root.get("components"))
        paths = root.get("paths")
        if isinstance(paths, dict):
            for template in paths:
                if template.startswith("x-"):
                    continue
                self.path_item(
                    path,
                    _child("/paths", template),
                    paths[template],
                    OperationSource.PATH,
                    template,
                    record_path=True,
                )
        webhooks = root.get("webhooks")
        if isinstance(webhooks, dict):
            for name in webhooks:
                pointer = _child("/webhooks", name)
                item = webhooks[name]
                resolved = self.deref(path, pointer, item)
                methods = ()
                if resolved is not None and isinstance(resolved[2], dict):
                    methods = tuple(sorted(m for m in resolved[2] if m in HTTP_METHODS_3_2))
                self.add(
                    "webhooks",
                    OpenApiWebhook(
                        location=self.loc(path, pointer),
                        pointer=pointer,
                        name=name,
                        methods=methods,
                        ref=_str(item.get("$ref")) if isinstance(item, dict) else None,
                    ),
                )
                self.path_item(
                    path, pointer, item, OperationSource.WEBHOOK, name, record_path=False
                )

    def servers(self, path: str, pointer: str, node: dict[str, Any]) -> None:
        servers = node.get("servers")
        if not isinstance(servers, list):
            return
        for index, server in enumerate(servers):
            server_pointer = f"{pointer}/servers/{index}"
            if isinstance(server, dict) and isinstance(server.get("url"), str):
                variables = server.get("variables")
                self.add(
                    "servers",
                    OpenApiServer(
                        location=self.loc(path, server_pointer),
                        pointer=server_pointer,
                        url=server["url"],
                        description=_str(server.get("description")),
                        variables=variables if isinstance(variables, dict) else None,
                    ),
                )

    def security(self, path: str, pointer: str, owner: str, node: dict[str, Any]) -> None:
        security = node.get("security")
        if not isinstance(security, list):
            return
        for index, requirement in enumerate(security):
            requirement_pointer = f"{pointer}/security/{index}"
            if not isinstance(requirement, dict):
                continue
            schemes = tuple(
                OpenApiSchemeUse(
                    name=str(name),
                    scopes=tuple(str(s) for s in scopes) if isinstance(scopes, list) else (),
                )
                for name, scopes in sorted(requirement.items())
            )
            self.add(
                "security_requirements",
                OpenApiSecurityRequirement(
                    location=self.loc(path, requirement_pointer),
                    pointer=requirement_pointer,
                    owner_pointer=owner,
                    schemes=schemes,
                ),
            )

    def external_docs(self, path: str, pointer: str, node: dict[str, Any]) -> None:
        docs = node.get("externalDocs")
        if isinstance(docs, dict):
            docs_pointer = f"{pointer}/externalDocs"
            self.add(
                "external_docs",
                OpenApiExternalDocs(
                    location=self.loc(path, docs_pointer),
                    pointer=docs_pointer,
                    url=_str(docs.get("url")),
                    description=_str(docs.get("description")),
                ),
            )

    def components(self, path: str, components: Any) -> None:
        if not isinstance(components, dict):
            return

        def entries(kind: str) -> Iterator[tuple[str, str, Any]]:
            section = components.get(kind)
            if isinstance(section, dict):
                for name in section:
                    yield name, _child(f"/components/{kind}", name), section[name]

        for name, pointer, schema in entries("schemas"):
            self.add(
                "schemas",
                OpenApiSchema(
                    location=self.loc(path, pointer), pointer=pointer, name=name, content=schema
                ),
            )
            if isinstance(schema, dict):
                self.external_docs(path, pointer, schema)
        for name, pointer, node in entries("parameters"):
            self.parameter(path, pointer, node, component_name=name)
        for name, pointer, node in entries("requestBodies"):
            self.request_body(path, pointer, node, component_name=name)
        for name, pointer, node in entries("responses"):
            self.response(path, pointer, node, status=None, component_name=name)
        for name, pointer, node in entries("callbacks"):
            self.callback(path, pointer, name, node, follow=False)
        for name, pointer, node in entries("securitySchemes"):
            resolved = self.deref(path, pointer, node)
            scheme = resolved[2] if resolved is not None else {}
            if not isinstance(scheme, dict):
                scheme = {}
            flows = scheme.get("flows")
            self.add(
                "security_schemes",
                OpenApiSecurityScheme(
                    location=self.loc(path, pointer),
                    pointer=pointer,
                    name=name,
                    type=_str(scheme.get("type")),
                    scheme=_str(scheme.get("scheme")),
                    bearer_format=_str(scheme.get("bearerFormat")),
                    location_in=_str(scheme.get("in")),
                    parameter_name=_str(scheme.get("name")),
                    open_id_connect_url=_str(scheme.get("openIdConnectUrl")),
                    flows=flows if isinstance(flows, dict) else None,
                    ref=_str(node.get("$ref")) if isinstance(node, dict) else None,
                ),
            )

    def parameter(
        self, path: str, pointer: str, node: Any, component_name: str | None = None
    ) -> None:
        resolved = self.deref(path, pointer, node)
        target = resolved[2] if resolved is not None and isinstance(resolved[2], dict) else {}
        self.add(
            "parameters",
            OpenApiParameter(
                location=self.loc(path, pointer),
                pointer=pointer,
                name=_str(target.get("name")),
                location_in=_str(target.get("in")),
                required=_bool(target.get("required")),
                deprecated=_bool(target.get("deprecated")),
                ref=_str(node.get("$ref")) if isinstance(node, dict) else None,
                schema=target.get("schema"),
                component_name=component_name,
            ),
        )

    def request_body(
        self, path: str, pointer: str, node: Any, component_name: str | None = None
    ) -> None:
        resolved = self.deref(path, pointer, node)
        target = resolved[2] if resolved is not None and isinstance(resolved[2], dict) else {}
        self.add(
            "request_bodies",
            OpenApiRequestBody(
                location=self.loc(path, pointer),
                pointer=pointer,
                required=_bool(target.get("required")),
                content_types=_content_types(target),
                ref=_str(node.get("$ref")) if isinstance(node, dict) else None,
                component_name=component_name,
            ),
        )

    def response(
        self,
        path: str,
        pointer: str,
        node: Any,
        status: str | None,
        component_name: str | None = None,
    ) -> None:
        resolved = self.deref(path, pointer, node)
        target = resolved[2] if resolved is not None and isinstance(resolved[2], dict) else {}
        self.add(
            "responses",
            OpenApiResponse(
                location=self.loc(path, pointer),
                pointer=pointer,
                status=status,
                description=_str(target.get("description")),
                content_types=_content_types(target),
                ref=_str(node.get("$ref")) if isinstance(node, dict) else None,
                component_name=component_name,
            ),
        )

    def callback(self, path: str, pointer: str, name: str, node: Any, *, follow: bool) -> None:
        resolved = self.deref(path, pointer, node)
        expressions: tuple[str, ...] = ()
        if resolved is not None and isinstance(resolved[2], dict):
            expressions = tuple(sorted(k for k in resolved[2] if not k.startswith("x-")))
        self.add(
            "callbacks",
            OpenApiCallback(
                location=self.loc(path, pointer),
                pointer=pointer,
                name=name,
                expressions=expressions,
                ref=_str(node.get("$ref")) if isinstance(node, dict) else None,
            ),
        )
        if follow and resolved is not None and isinstance(resolved[2], dict):
            cb_path, cb_pointer, cb = resolved
            for expression in expressions:
                self.path_item(
                    cb_path,
                    _child(cb_pointer, expression),
                    cb[expression],
                    OperationSource.CALLBACK,
                    expression,
                    record_path=False,
                )

    def path_item(
        self,
        path: str,
        pointer: str,
        node: Any,
        source: OperationSource,
        name: str,
        *,
        record_path: bool,
    ) -> None:
        resolved = self.deref(path, pointer, node)
        if record_path:
            item_for_meta = resolved[2] if resolved is not None else {}
            if not isinstance(item_for_meta, dict):
                item_for_meta = {}
            self.add(
                "paths",
                OpenApiPathItem(
                    location=self.loc(path, pointer),
                    pointer=pointer,
                    path=name,
                    ref=_str(node.get("$ref")) if isinstance(node, dict) else None,
                    summary=_str(item_for_meta.get("summary")),
                    description=_str(item_for_meta.get("description")),
                ),
            )
        if resolved is None or not isinstance(resolved[2], dict):
            return
        item_path, item_pointer, item = resolved
        key = (item_path, item_pointer, source.value, name)
        if key in self.visited_items:
            return
        self.visited_items.add(key)
        self.servers(item_path, item_pointer, item)
        item_params = self.parameter_list(item_path, item_pointer, item)
        operations: list[tuple[str, str, Any]] = [
            (method, _child(item_pointer, method), item[method])
            for method in HTTP_METHODS_3_2
            if method in item
        ]
        additional = item.get("additionalOperations")
        if isinstance(additional, dict):
            base = _child(item_pointer, "additionalOperations")
            operations.extend((m, _child(base, m), additional[m]) for m in additional)
        for method, op_pointer, op in operations:
            if not isinstance(op, dict):
                continue
            self.operation(item_path, op_pointer, method, op, source, name, item_params)

    def parameter_list(self, path: str, pointer: str, node: dict[str, Any]) -> tuple[str, ...]:
        params = node.get("parameters")
        pointers: list[str] = []
        if isinstance(params, list):
            for index, param in enumerate(params):
                param_pointer = f"{pointer}/parameters/{index}"
                pointers.append(param_pointer)
                self.parameter(path, param_pointer, param)
        return tuple(pointers)

    def operation(
        self,
        path: str,
        pointer: str,
        method: str,
        op: dict[str, Any],
        source: OperationSource,
        name: str,
        inherited: tuple[str, ...],
    ) -> None:
        operation_id = _str(op.get("operationId"))
        params = self.parameter_list(path, pointer, op)
        body_pointer = None
        if "requestBody" in op:
            body_pointer = f"{pointer}/requestBody"
            self.request_body(path, body_pointer, op["requestBody"])
        response_pointers: list[str] = []
        responses = op.get("responses")
        if isinstance(responses, dict):
            for status in responses:
                if status.startswith("x-"):
                    continue
                response_pointer = _child(f"{pointer}/responses", status)
                response_pointers.append(response_pointer)
                self.response(path, response_pointer, responses[status], status=status)
        callback_pointers: list[str] = []
        callbacks = op.get("callbacks")
        if isinstance(callbacks, dict):
            for cb_name in callbacks:
                if cb_name.startswith("x-"):
                    continue
                cb_pointer = _child(f"{pointer}/callbacks", cb_name)
                callback_pointers.append(cb_pointer)
                self.callback(path, cb_pointer, cb_name, callbacks[cb_name], follow=True)
        self.servers(path, pointer, op)
        self.security(path, pointer, pointer, op)
        self.external_docs(path, pointer, op)
        tags = op.get("tags")
        identity_path = name if source is OperationSource.PATH else f"{source.value.lower()}:{name}"
        self.add(
            "operations",
            OpenApiOperation(
                location=self.loc(path, pointer),
                pointer=pointer,
                source=source,
                method=method.upper(),
                path=name,
                identity=operation_identity(method, identity_path, operation_id),
                operation_id=operation_id,
                summary=_str(op.get("summary")),
                description=_str(op.get("description")),
                deprecated=_bool(op.get("deprecated")),
                tags=tuple(t for t in tags if isinstance(t, str)) if isinstance(tags, list) else (),
                parameter_pointers=(*inherited, *params),
                request_body_pointer=body_pointer,
                response_pointers=tuple(response_pointers),
                callback_pointers=tuple(callback_pointers),
                has_security="security" in op,
            ),
        )

    # -- entry --------------------------------------------------------------

    def run(self, paths: Sequence[str] | None) -> OpenApiProjectModel:
        explicit = paths is not None
        if paths is None:
            candidates = [
                p
                for p in self.context.iter_files()
                if p.lower().endswith(CANDIDATE_SUFFIXES) and not _skipped(p)
            ]
        else:
            candidates = sorted({p.replace("\\", "/") for p in paths})
        roots: list[_Doc] = []
        for candidate in candidates:
            doc = self.load(candidate, root=True, explicit=explicit)
            if doc is not None:
                roots.append(doc)
        for doc in roots:
            if doc.status is DocumentStatus.PARSED and doc.path not in self.walked:
                self.walked.add(doc.path)
                self.walk(doc)
        self.resolve_sites(0)
        self.detect_cycles()
        for doc in roots:
            if doc.status is DocumentStatus.PARSED:
                self.extract(doc)
            else:
                self.add(
                    "documents",
                    OpenApiDocument(
                        location=self.loc(doc.path),
                        format=doc.fmt,
                        status=doc.status,
                        openapi_version=doc.version,
                    ),
                )
        root_paths = {doc.path for doc in roots}
        for doc in self.docs.values():
            if doc.path not in root_paths:
                self.add(
                    "documents",
                    OpenApiDocument(location=self.loc(doc.path), format=doc.fmt, status=doc.status),
                )
        out = self.out
        return OpenApiProjectModel(
            schema_version=OPENAPI_MODEL_SCHEMA_VERSION,
            documents=_unique_sorted(out.get("documents", [])),
            servers=_unique_sorted(out.get("servers", [])),
            paths=_unique_sorted(out.get("paths", [])),
            operations=_unique_sorted(out.get("operations", [])),
            parameters=_unique_sorted(out.get("parameters", [])),
            request_bodies=_unique_sorted(out.get("request_bodies", [])),
            responses=_unique_sorted(out.get("responses", [])),
            schemas=_unique_sorted(out.get("schemas", [])),
            callbacks=_unique_sorted(out.get("callbacks", [])),
            webhooks=_unique_sorted(out.get("webhooks", [])),
            security_schemes=_unique_sorted(out.get("security_schemes", [])),
            security_requirements=_unique_sorted(out.get("security_requirements", [])),
            tags=_unique_sorted(out.get("tags", [])),
            external_docs=_unique_sorted(out.get("external_docs", [])),
            extensions=_unique_sorted(out.get("extensions", [])),
            references=_unique_sorted(out.get("references", [])),
            unresolved_external_refs=_unique_sorted(out.get("unresolved", [])),
            cycles=_unique_sorted(out.get("cycles", [])),
            issues=_unique_sorted(self.issues),
        )


def load_openapi_project(
    context: ProjectContext, paths: Sequence[str] | None = None
) -> OpenApiProjectModel:
    """Parse OpenAPI documents under `context` into an `OpenApiProjectModel`.

    With `paths=None`, discovers `*.yaml`/`*.yml`/`*.json` files (skipping
    hidden and vendor directories) and keeps only those passing the detection
    gate (or malformed files that carry an `openapi:` marker). With explicit
    `paths`, every listed file is reported, including NOT_OPENAPI ones.
    Never raises on bad input; never touches the network.
    """
    return _Builder(context).run(paths)


__all__ = ["load_openapi_project"]
