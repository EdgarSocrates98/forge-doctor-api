"""Python client extractor: `requests`/`httpx` call sites via `ast` (§17).

- `import requests as r` -> `r.get(...)`, `r.request("GET", ...)`
- `import httpx` / `from httpx import Client` -> `c = httpx.Client()` bound
  vars -> `c.get(...)`
- response fields: `resp.json()["field"]`, `resp.json().get("f")`,
  `d = resp.json(); d["f"]`, and chained `r.get(u).json()["f"]`.
- non-literal URLs/methods -> `ClientScan.unknowns`, never guessed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from forge_doctor_api.analyzers.clients.model import (
    ClientCallSite,
    ClientLanguage,
    client_name_for,
)
from forge_doctor_api.core.models import SourceLocation, UnknownFact

_HTTP_METHODS = frozenset(
    {"get", "post", "put", "delete", "patch", "head", "options", "request"}
)
_CLIENT_CTOR = frozenset({"Client", "AsyncClient", "Session"})


@dataclass(frozen=True)
class _Site:
    call: ast.Call
    library: str
    method: str | None
    url_node: ast.expr | None


def _loc(path: str, node: ast.AST) -> SourceLocation:
    return SourceLocation(
        path=path, line=getattr(node, "lineno", 1), column=getattr(node, "col_offset", 0) + 1
    )


def _literal(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _url_path(url: str) -> str | None:
    """Strip scheme+host and query from a literal URL."""
    rest = url
    if "://" in rest:
        rest = rest.split("://", 1)[1]
        rest = rest.partition("/")[2]
        rest = "/" + rest if rest else "/"
    if not rest.startswith("/"):
        rest = "/" + rest
    return rest.split("?", 1)[0] or None


def _binding_target(node: ast.AST) -> str | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        t = node.targets[0]
        return t.id if isinstance(t, ast.Name) else None
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def scan_python_source(path: str, source: str) -> tuple[list[ClientCallSite], list[UnknownFact]]:
    """Extract client call sites from one Python module's source."""
    sites: list[ClientCallSite] = []
    unknowns: list[UnknownFact] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return sites, unknowns

    aliases: dict[str, str] = {}
    alias_methods: dict[str, str] = {}
    # spec 087 — generated-client surfaces: gRPC stubs (`*_pb2_grpc`/
    # `*_grpc` imports + `Stub(channel)` bindings + `stub.Rpc(...)`) and
    # generated OpenAPI clients (`openapi_client`/`*_api` imports +
    # `*Api(...)` bindings + `api.operation(...)`).
    stub_classes: dict[str, str] = {}   # bound name -> module
    api_classes: dict[str, str] = {}    # bound name -> module
    grpc_modules: dict[str, str] = {}   # alias -> *_pb2_grpc module
    gen_modules: dict[str, str] = {}    # alias -> generated client module

    def _is_grpc_mod(mod: str) -> bool:
        return mod.endswith(("_pb2_grpc", "_grpc")) or "_pb2_grpc" in mod

    def _is_gen_mod(mod: str) -> bool:
        parts = mod.split(".")
        return "openapi_client" in parts or any(
            p.endswith("_api") for p in parts)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name
                if alias.name in ("requests", "httpx"):
                    aliases[bound] = alias.name
                elif _is_grpc_mod(alias.name):
                    grpc_modules[bound] = alias.name
                elif _is_gen_mod(alias.name):
                    gen_modules[bound] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module in ("requests", "httpx"):
                for alias in node.names:
                    if alias.name in _CLIENT_CTOR:
                        aliases.setdefault(f"__ctor__.{alias.asname or alias.name}", node.module)
                    elif alias.name in _HTTP_METHODS:
                        bound = alias.asname or alias.name
                        aliases[bound] = node.module
                        alias_methods[bound] = alias.name.upper()
            elif _is_grpc_mod(node.module):
                for alias in node.names:
                    if alias.name.endswith("Stub"):
                        stub_classes[alias.asname or alias.name] = node.module
            elif _is_gen_mod(node.module):
                for alias in node.names:
                    bound = alias.asname or alias.name
                    if alias.name.endswith(("Api", "API")):
                        api_classes[bound] = node.module
                    else:
                        gen_modules[bound] = node.module

    # session/client variable bindings: `c = httpx.Client(...)`, `c = Client()`
    client_vars: dict[str, str] = {}
    stub_vars: dict[str, str] = {}   # var -> stub module (gRPC)
    api_vars: dict[str, str] = {}    # var -> client module (generated OpenAPI)
    response_vars: dict[str, ast.expr] = {}
    data_vars: set[str] = set()
    for node in ast.walk(tree):
        target = _binding_target(node)
        value = node.value if isinstance(node, ast.Assign | ast.AnnAssign) else None
        if target is None or not isinstance(value, ast.Call):
            continue
        func = value.func
        # gRPC stub ctor: `s = GreeterStub(channel)` / `s = x_pb2_grpc.GreeterStub(ch)`
        if isinstance(func, ast.Name) and func.id in stub_classes:
            stub_vars[target] = stub_classes[func.id]
            continue
        if (
            isinstance(func, ast.Attribute)
            and func.attr.endswith("Stub")
            and isinstance(func.value, ast.Name)
            and func.value.id in grpc_modules
        ):
            stub_vars[target] = grpc_modules[func.value.id]
            continue
        # generated OpenAPI client ctor: `api = PetApi(...)` / `api = pet_api.PetApi()`
        if isinstance(func, ast.Name) and func.id in api_classes:
            api_vars[target] = api_classes[func.id]
            continue
        if (
            isinstance(func, ast.Attribute)
            and func.attr.endswith(("Api", "API"))
            and isinstance(func.value, ast.Name)
            and func.value.id in gen_modules
        ):
            api_vars[target] = gen_modules[func.value.id]
            continue
        # client constructor bindings
        ctor_lib: str | None = None
        if isinstance(func, ast.Attribute) and func.attr in _CLIENT_CTOR:
            base = func.value
            if isinstance(base, ast.Name) and aliases.get(base.id) in ("requests", "httpx"):
                ctor_lib = aliases[base.id]
        elif isinstance(func, ast.Name) and f"__ctor__.{func.id}" in aliases:
            ctor_lib = aliases[f"__ctor__.{func.id}"]
        if ctor_lib:
            client_vars[target] = ctor_lib
            continue
        # response bindings: `resp = requests.get(...)` style
        lib = _call_library(func, aliases, client_vars)
        if lib:
            response_vars[target] = value
        # data bindings: `d = resp.json()`
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "json"
            and isinstance(func.value, ast.Name)
            and func.value.id in response_vars
        ):
            data_vars.add(target)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # gRPC stub / generated-client calls carry an operation name,
        # never a literal URL — emit before the HTTP branch.
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            receiver = func.value.id
            if receiver in stub_vars:
                sites.append(ClientCallSite(
                    client=client_name_for(path),
                    language=ClientLanguage.PYTHON,
                    library="grpc-stub",
                    method=None, url=None, path=None,
                    operation=func.attr,
                    location=_loc(path, node),
                ))
                continue
            if receiver in api_vars:
                sites.append(ClientCallSite(
                    client=client_name_for(path),
                    language=ClientLanguage.PYTHON,
                    library="openapi-generated",
                    method=None, url=None, path=None,
                    operation=func.attr,
                    location=_loc(path, node),
                ))
                continue
        library: str | None = None
        method: str | None = None
        url_node: ast.expr | None = None
        if isinstance(func, ast.Name) and func.id in alias_methods:
            library = aliases[func.id]
            method = alias_methods[func.id]
            url_node = node.args[0] if node.args else None
        elif isinstance(func, ast.Attribute):
            base = func.value
            if func.attr in _HTTP_METHODS:
                if isinstance(base, ast.Name) and base.id in aliases:
                    library = aliases[base.id]
                elif isinstance(base, ast.Name) and base.id in client_vars:
                    library = client_vars[base.id]
                if library and func.attr == "request":
                    method = _literal(node.args[0]) if node.args else None
                    url_node = node.args[1] if len(node.args) > 1 else None
                    method = method.upper() if method else None
                elif library:
                    method = func.attr.upper()
                    url_node = node.args[0] if node.args else None
        if library is None:
            continue
        url = _literal(url_node)
        if url is None:
            unknowns.append(
                UnknownFact(
                    subject=f"{path}:{node.lineno}",
                    missing="literal URL/method for the client call",
                    resolution="the call uses a computed URL or dynamic dispatch",
                )
            )
            continue
        fields = _response_fields(tree, node, response_vars, data_vars)
        sites.append(
            ClientCallSite(
                client=client_name_for(path),
                language=ClientLanguage.PYTHON,
                library=library,
                method=method,
                url=url,
                path=_url_path(url),
                response_fields=tuple(sorted(fields)),
                location=_loc(path, node),
            )
        )
    return sites, unknowns


def _call_library(
    func: ast.expr, aliases: dict[str, str], client_vars: dict[str, str]
) -> str | None:
    if isinstance(func, ast.Attribute) and func.attr in _HTTP_METHODS:
        base = func.value
        if isinstance(base, ast.Name):
            return aliases.get(base.id) or client_vars.get(base.id)
    return None


def _response_fields(
    tree: ast.AST,
    call: ast.Call,
    response_vars: dict[str, ast.expr],
    data_vars: set[str],
) -> set[str]:
    """Field names read off this call's response via `.json()` (§183 evidence)."""
    fields: set[str] = set()
    call_funcs = {
        node.func for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    resp_names = {name for name, expr in response_vars.items() if expr is call}
    for node in ast.walk(tree):
        # resp.json()["field"] / data["field"] / data.get("field") / data.field
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and len(node.args) >= 1
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in data_vars | resp_names
        ):
            key = _literal(node.args[0])
            if key:
                fields.add(key)
        if isinstance(node, ast.Subscript):
            key = _literal(node.slice)
            owner = node.value
            name: str | None = None
            if isinstance(owner, ast.Name):
                name = owner.id
            elif (
                isinstance(owner, ast.Call)
                and isinstance(owner.func, ast.Attribute)
                and owner.func.attr == "json"
                and isinstance(owner.func.value, ast.Name)
            ):
                name = owner.func.value.id
            if key and name in data_vars | resp_names:
                fields.add(key)
        # direct chain: requests.get(u).json()["f"] or resp.json()["f"]
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "json"
            and isinstance(node.value.func.value, ast.Call)
        ):
            inner = node.value.func.value
            if inner is call:
                key = _literal(node.slice)
                if key:
                    fields.add(key)
        # attribute access on bound json data: data.email (but not data.get(...))
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in data_vars
            and node not in call_funcs
        ):
            fields.add(node.attr)
    return fields
