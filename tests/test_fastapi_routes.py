"""FastAPI route discovery tests (spec 006, §195).

Coverage per §202: positive extraction, negative attribution, and §100
adversarial inputs — decorator-shaped comments/strings, dynamic route
tables, generated directories, unresolvable imports.
"""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.routes import (
    FastApiAdapter,
    ResponseSchemaSource,
    scan_graph,
)
from forge_doctor_api.core.context import ProjectContext

APP = '''
from fastapi import FastAPI

app = FastAPI()
'''

ROUTER = '''
from fastapi import APIRouter

router = APIRouter(prefix="/v1")
'''


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _scan(root: Path, service: str = "svc", paths: list[str] | None = None):
    return FastApiAdapter().scan(ProjectContext.from_root(root), service, paths)


def _routes(scan):
    return {(r.method, r.path): r for r in scan.routes}


# -- attribution gate ---------------------------------------------------------


def test_attributes_strong_markers(tmp_path: Path) -> None:
    _write(tmp_path, {"main.py": APP + '@app.get("/x")\ndef x(): ...\n'})
    scan = _scan(tmp_path)
    assert [a.path for a in scan.attributions] == ["main.py"]


def test_import_only_does_not_attribute(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {"a.py": "from fastapi import FastAPI\n\n\n@something.get('/x')\ndef x(): ...\n"},
    )
    scan = _scan(tmp_path)
    assert scan.attributions == () and scan.routes == ()


def test_instantiation_only_does_not_attribute(tmp_path: Path) -> None:
    _write(tmp_path, {"a.py": "app = FastAPI()\n\n\n@app.get('/x')\ndef x(): ...\n"})
    scan = _scan(tmp_path)
    assert scan.attributions == () and scan.routes == ()


def test_decorator_like_comments_and_strings(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "a.py": (
                "# @app.get('/fake')\n"
                "x = '''\n@router.post('/also-fake')\ndef f(): ...\n'''\n"
                "doc = '@app.delete(\"/nope\")'\n"
            )
        },
    )
    scan = _scan(tmp_path)
    assert scan.attributions == () and scan.routes == ()


def test_lookalike_framework_not_attributed(tmp_path: Path) -> None:
    """`flask`-style app with no fastapi import must yield nothing."""
    _write(
        tmp_path,
        {
            "a.py": (
                "from flask import Flask\n\napp = Flask(__name__)\n\n"
                "@app.get('/x')\ndef x(): ...\n"
            )
        },
    )
    scan = _scan(tmp_path)
    assert scan.attributions == () and scan.routes == ()


def test_generated_dir_skipped(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {"generated/api.py": APP + '@app.get("/gen")\ndef g(): ...\n'},
    )
    scan = _scan(tmp_path)
    assert scan.routes == ()


# -- route extraction ----------------------------------------------------------


def test_decorator_methods_and_path(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "main.py": APP
            + """
@app.get("/a")
def a(): ...
@app.put("/b/{b_id}")
def b(b_id: int): ...
@app.delete("/c", status_code=204)
def c(): ...
"""
        },
    )
    routes = _routes(_scan(tmp_path))
    assert ("GET", "/a") in routes and ("PUT", "/b/{b_id}") in routes
    assert ("DELETE", "/c") in routes
    assert routes[("DELETE", "/c")].status_codes == ("204",)
    assert routes[("GET", "/a")].source_location.line is not None


def test_all_http_methods(tmp_path: Path) -> None:
    body = APP + "".join(
        f'@app.{m}("/{m}")\ndef h_{m}(): ...\n'
        for m in ("get", "post", "put", "delete", "patch", "options", "head", "trace")
    )
    _write(tmp_path, {"main.py": body})
    routes = _routes(_scan(tmp_path))
    assert len(routes) == 8


def test_router_prefix_and_include_chain(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "main.py": (
                "from fastapi import FastAPI\n"
                "from routers import items\n\n"
                "app = FastAPI(root_path=\"/prod\")\n"
                "app.include_router(items.router, prefix=\"/api\")\n"
            ),
            "routers/items.py": ROUTER
            + """
@router.get("/{item_id}")
def get_item(item_id: int): ...
""",
        },
    )
    routes = _routes(_scan(tmp_path))
    assert ("GET", "/prod/api/v1/{item_id}") in routes


def test_nested_include_router(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "main.py": (
                "from fastapi import FastAPI\n"
                "import mid\n\n"
                "app = FastAPI()\n"
                "app.include_router(mid.outer, prefix=\"/api\")\n"
            ),
            "mid.py": (
                "from fastapi import APIRouter\n"
                "import inner\n\n"
                "outer = APIRouter(prefix=\"/o\")\n"
                "outer.include_router(inner.router, prefix=\"/i\")\n"
            ),
            "inner.py": ROUTER.replace('"/v1"', '"/leaf"')
            + """
@router.get("/deep")
def deep(): ...
""",
        },
    )
    routes = _routes(_scan(tmp_path))
    assert ("GET", "/api/o/i/leaf/deep") in routes


def test_unattached_router_still_reports_routes(tmp_path: Path) -> None:
    _write(tmp_path, {"r.py": ROUTER + '@router.get("/loose")\ndef f(): ...\n'})
    routes = _routes(_scan(tmp_path))
    assert ("GET", "/v1/loose") in routes


def test_path_kwarg_and_relative_import(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "main.py": (
                "from fastapi import FastAPI\n"
                "from .routers import items\n\n"
                "app = FastAPI()\n"
                "app.include_router(items.router)\n"
            ),
            "routers/items.py": ROUTER
            + """
@router.get(path="/kw")
def kw(): ...
""",
        },
    )
    routes = _routes(_scan(tmp_path))
    assert ("GET", "/v1/kw") in routes


# -- schema + auth discovery ----------------------------------------------------


def test_response_model_and_return_annotation(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "main.py": APP
            + """
from pydantic import BaseModel


class Out(BaseModel): ...


@app.get("/a", response_model=Out)
def a(): ...


@app.get("/b")
def b() -> Out: ...
"""
        },
    )
    routes = _routes(_scan(tmp_path))
    assert routes[("GET", "/a")].response_schema == "Out"
    assert routes[("GET", "/a")].response_schema_source is ResponseSchemaSource.RESPONSE_MODEL
    assert routes[("GET", "/b")].response_schema == "Out"
    assert routes[("GET", "/b")].response_schema_source is ResponseSchemaSource.RETURN_ANNOTATION


def test_request_schema_from_pydantic_param(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "main.py": APP
            + """
from pydantic import BaseModel


class In(BaseModel): ...


@app.post("/a")
def a(payload: In, q: int): ...
"""
        },
    )
    routes = _routes(_scan(tmp_path))
    assert routes[("POST", "/a")].request_schema == "main.In"


def test_scalar_params_are_not_request_schemas(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {"main.py": APP + '@app.get("/a/{n}")\ndef a(n: int, q: str = ""): ...\n'},
    )
    routes = _routes(_scan(tmp_path))
    assert routes[("GET", "/a/{n}")].request_schema is None


def test_auth_and_dependencies_evidence(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "main.py": APP.replace(
                "app = FastAPI()",
                "app = FastAPI()\napp.add_middleware(GZipMiddleware)",
            )
            + """
from fastapi import Security, Depends


@app.get("/s", dependencies=[Depends(audit)])
def s(user=Security(current_user), db=Depends(get_db)): ...
"""
        },
    )
    routes = _routes(_scan(tmp_path))
    route = routes[("GET", "/s")]
    assert route.auth == ("current_user",)
    assert "audit" in route.middleware and "get_db" in route.middleware
    assert "GZipMiddleware" in route.middleware


# -- dynamic / adversarial ------------------------------------------------------


def test_dynamic_path_recorded_as_unknown(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {"main.py": APP + 'P = "/x"\n\n\n@app.get(P)\ndef x(): ...\n'},
    )
    scan = _scan(tmp_path)
    assert scan.routes == ()
    assert any("dynamic" in u.missing for u in scan.unknowns)


def test_dynamic_include_prefix_unknown(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "main.py": (
                "from fastapi import FastAPI\n"
                "from routers import items\n\n"
                "app = FastAPI()\n"
                "P = computed()\n"
                "app.include_router(items.router, prefix=P)\n"
            ),
            "routers/items.py": ROUTER + '@router.get("/i")\ndef i(): ...\n',
        },
    )
    scan = _scan(tmp_path)
    assert any("include_router" in u.missing for u in scan.unknowns)


def test_routes_in_loops_are_unknown_not_guessed(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "main.py": APP
            + """
for p in routes_table:
    @app.get(p)
    def h(): ...
"""
        },
    )
    scan = _scan(tmp_path)
    assert scan.routes == ()
    assert any("dynamic" in u.missing for u in scan.unknowns)


def test_add_api_route_literal(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "main.py": APP
            + """
def handler(): ...

app.add_api_route("/explicit", handler, methods=["GET", "POST"])
"""
        },
    )
    routes = _routes(_scan(tmp_path))
    assert ("GET", "/explicit") in routes and ("POST", "/explicit") in routes
    assert routes[("GET", "/explicit")].handler == "handler"


def test_syntax_error_unknown(tmp_path: Path) -> None:
    _write(tmp_path, {"broken.py": "def broken(:\nfrom fastapi import FastAPI\napp = FastAPI()\n"})
    scan = _scan(tmp_path)
    assert scan.routes == ()
    assert any("parseable" in u.missing for u in scan.unknowns)


def test_unparseable_file_never_imported(tmp_path: Path) -> None:
    """The adapter must never import/execute target code (§1)."""
    _write(
        tmp_path,
        {
            "main.py": APP
            + 'import os\nos._exit(0) if True else None\n@app.get("/x")\ndef x(): ...\n'
        },
    )
    scan = _scan(tmp_path)
    assert ("GET", "/x") in _routes(scan)


# -- graph emission -------------------------------------------------------------


def test_scan_graph_entities_and_edges(tmp_path: Path) -> None:
    _write(tmp_path, {"main.py": APP + '@app.get("/x")\ndef x(): ...\n'})
    graph = scan_graph(_scan(tmp_path))
    ids = {e.id for e in graph.entities()}
    assert "service:python:svc" in ids
    assert "endpoint:http:GET /x" in ids
    assert "operation:fastapi:main.x" in ids
    edges = {(r.kind, r.source_id, r.target_id) for r in graph.relationships()}
    assert ("EXPOSES", "service:python:svc", "endpoint:http:GET /x") in edges
    assert ("IMPLEMENTS", "operation:fastapi:main.x", "endpoint:http:GET /x") in edges


def test_no_entities_for_unattributed_files(tmp_path: Path) -> None:
    _write(tmp_path, {"a.py": "def f(): ...\n"})
    graph = scan_graph(_scan(tmp_path))
    assert [e for e in graph.entities() if e.kind != "service"] == []


# -- determinism -----------------------------------------------------------------


def test_deterministic_across_file_orders(tmp_path: Path) -> None:
    files = {
        "a_main.py": (
            "from fastapi import FastAPI\n"
            "import b_router\n\n"
            "app = FastAPI()\n"
            "app.include_router(b_router.router, prefix=\"/api\")\n"
        ),
        "b_router.py": ROUTER + '@router.get("/r")\ndef r(): ...\n',
        "c_extra.py": APP + '@app.post("/p")\ndef p(): ...\n',
    }
    _write(tmp_path, files)
    first = _scan(tmp_path).to_json()
    second = _scan(tmp_path, paths=["c_extra.py", "b_router.py", "a_main.py"]).to_json()
    assert first == second
