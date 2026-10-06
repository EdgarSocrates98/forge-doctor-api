"""Client discovery + impact tests (spec 009, §17, §68, §183, §226).

Confirmed impact requires field-level usage evidence — endpoint consumption
alone only yields `CLIENT002` (§183).
"""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.clients import client_graph, scan_clients
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.checks.client import client_impact
from forge_doctor_api.checks.compat import diff_models
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import RelationshipKind
from test_compat import USER_NEW, USER_OLD


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _clients(root: Path, files: dict[str, str]):
    _write(root, files)
    return scan_clients(ProjectContext.from_root(root), list(files))


def _ids(report) -> list[str]:
    return [f.id for f in report.findings]


# -- Python extraction -----------------------------------------------------------


PY_BASIC = '''
import requests

def load():
    return requests.get("https://api.example.com/users/42")
'''


def test_python_requests_get(tmp_path: Path) -> None:
    model = _clients(tmp_path, {"frontend-service/api.py": PY_BASIC})
    (site,) = model.call_sites
    assert site.library == "requests"
    assert site.method == "GET"
    assert site.path == "/users/42"
    assert site.client == "frontend-service"
    assert model.clients == ("frontend-service",)


def test_python_alias_and_httpx(tmp_path: Path) -> None:
    files = {
        "app/a.py": '''
import requests as r
r.post("http://x.internal/pets")
''',
        "app/b.py": '''
from requests import get
get("/users/1")
''',
        "app/c.py": '''
import httpx
client = httpx.Client()
client.delete("https://api/x/pets/9")
''',
    }
    model = _clients(tmp_path, files)
    methods = {(s.library, s.method, s.path) for s in model.call_sites}
    assert ("requests", "POST", "/pets") in methods
    assert ("requests", "GET", "/users/1") in methods
    assert ("httpx", "DELETE", "/x/pets/9") in methods


def test_python_dynamic_url_is_unknown(tmp_path: Path) -> None:
    model = _clients(tmp_path, {"web/c.py": '''
import requests
uid = 5
requests.get(f"https://api/users/{uid}")
requests.get(BASE + "/pets")
'''})
    assert model.call_sites == ()
    assert len(model.unknowns) == 2


def test_python_response_fields(tmp_path: Path) -> None:
    model = _clients(tmp_path, {"frontend-service/u.py": '''
import requests
resp = requests.get("https://api.example.com/users/42")
data = resp.json()
print(data["email"], data.get("name"), data.id)
'''})
    (site,) = model.call_sites
    assert set(site.response_fields) == {"email", "name", "id"}


def test_python_comment_is_not_a_call(tmp_path: Path) -> None:
    model = _clients(tmp_path, {"x/c.py": '''
# requests.get("https://api/fake")
s = "httpx.post(\\"https://api/fake\\")"
import requests
requests.get("/real")
'''})
    assert [s.path for s in model.call_sites] == ["/real"]


# -- JS/TS extraction ------------------------------------------------------------


def test_js_fetch_and_axios(tmp_path: Path) -> None:
    model = _clients(tmp_path, {"web/lib.ts": '''
const a = fetch("https://api.example.com/users/7")
const b = fetch('/pets', { method: 'POST' })
axios.delete("https://api/pets/3")
axios({ method: 'put', url: '/pets/4' })
fetch(`https://api/users/${id}`)
// fetch("https://api/commented")
'''})
    by_method = {(s.library, s.method, s.path) for s in model.call_sites}
    assert ("fetch", "GET", "/users/7") in by_method
    assert ("fetch", "POST", "/pets") in by_method
    assert ("axios", "DELETE", "/pets/3") in by_method
    assert ("axios", "PUT", "/pets/4") in by_method
    assert len(model.call_sites) == 4
    assert len(model.unknowns) == 1  # template literal only


def test_js_response_fields(tmp_path: Path) -> None:
    model = _clients(tmp_path, {"web/u.js": '''
const resp = await fetch("https://api/users/42")
const data = await resp.json()
console.log(data.email, data["name"])
fetch("https://api/pets").then(r => r.json()).then(d => d.tag)
'''})
    by_path = {s.path: s for s in model.call_sites}
    assert {"email", "name"} <= set(by_path["/users/42"].response_fields)
    assert "tag" in by_path["/pets"].response_fields


# -- path matching ----------------------------------------------------------------


def test_template_path_matching(tmp_path: Path) -> None:
    diff = diff_models(
        _spec(tmp_path / "o", USER_OLD), _spec(tmp_path / "n", USER_NEW)
    )
    clients = _clients(tmp_path / "c", {"frontend-service/u.py": PY_BASIC})
    report = client_impact(diff, clients, _spec(tmp_path / "o", USER_OLD))
    assert [e.clients for e in report.entries] == [("frontend-service",)]


def _spec(root: Path, text: str):
    _write(root, {"openapi.yaml": text})
    return load_openapi_project(ProjectContext.from_root(root), ["openapi.yaml"])


# -- impact classification --------------------------------------------------------


def test_confirmed_impact_when_client_reads_removed_field(tmp_path: Path) -> None:
    diff = diff_models(
        _spec(tmp_path / "o", USER_OLD), _spec(tmp_path / "n", USER_NEW)
    )
    clients = _clients(tmp_path / "c", {"frontend-service/u.py": '''
import requests
resp = requests.get("https://api.example.com/users/42")
print(resp.json()["email"])
'''})
    report = client_impact(diff, clients, _spec(tmp_path / "o", USER_OLD))
    assert "CLIENT001" in _ids(report)
    assert report.entries[0].confirmed


def test_potential_impact_without_field_usage(tmp_path: Path) -> None:
    diff = diff_models(
        _spec(tmp_path / "o", USER_OLD), _spec(tmp_path / "n", USER_NEW)
    )
    clients = _clients(tmp_path / "c", {"frontend-service/u.py": PY_BASIC})
    report = client_impact(diff, clients, _spec(tmp_path / "o", USER_OLD))
    assert "CLIENT002" in _ids(report)
    assert "CLIENT001" not in _ids(report)
    assert not report.entries[0].confirmed


def test_unrelated_client_is_not_in_blast_radius(tmp_path: Path) -> None:
    diff = diff_models(
        _spec(tmp_path / "o", USER_OLD), _spec(tmp_path / "n", USER_NEW)
    )
    clients = _clients(tmp_path / "c", {"other/x.py": '''
import requests
requests.get("https://api.example.com/orders/1")
'''})
    report = client_impact(diff, clients, _spec(tmp_path / "o", USER_OLD))
    assert report.entries == ()
    assert report.findings == ()


def test_unresolvable_site_finding(tmp_path: Path) -> None:
    diff = diff_models(
        _spec(tmp_path / "o", USER_OLD), _spec(tmp_path / "n", USER_NEW)
    )
    clients = _clients(tmp_path / "c", {"svc/x.py": '''
import requests
requests.get(BASE + path)
'''})
    report = client_impact(diff, clients, _spec(tmp_path / "o", USER_OLD))
    assert "CLIENT003" in _ids(report)
    assert report.findings[0].unknowns


# -- graph + §226 demo ------------------------------------------------------------


def test_client_graph_consumes_edges(tmp_path: Path) -> None:
    model = _clients(tmp_path, {"frontend-service/u.py": PY_BASIC})
    graph = client_graph(model)
    kinds = {r.kind for r in graph.relationships()}
    assert RelationshipKind.CONSUMES in kinds
    assert any(
        e.kind == "client" and e.name == "frontend-service" for e in graph.entities()
    )


def test_section_226_demo(tmp_path: Path) -> None:
    """FastAPI service + openapi.yaml + client repo -> breaking + known client."""
    service = '''
from fastapi import FastAPI

app = FastAPI()

@app.get("/users/{id}")
def get_user(id: int):
    return {}
'''
    root = tmp_path / "repo"
    _write(root, {"service/main.py": service, "openapi.yaml": USER_OLD})
    _write(root, {"frontend-service/client.py": '''
import requests
resp = requests.get("https://api.example.com/users/42")
email = resp.json()["email"]
'''})
    ctx = ProjectContext.from_root(root)
    old = load_openapi_project(ctx, ["openapi.yaml"])
    new_root = tmp_path / "repo-next"
    _write(new_root, {"openapi.yaml": USER_NEW})
    new = load_openapi_project(
        ProjectContext.from_root(new_root), ["openapi.yaml"]
    )
    diff = diff_models(old, new)
    breaking = [c for c in diff.changes if c.classification.value == "BREAKING"]
    assert breaking and "getUser" in breaking[0].subject

    clients = scan_clients(ctx, ["frontend-service/client.py"])
    report = client_impact(diff, clients, old)
    assert report.entries[0].confirmed
    assert report.entries[0].clients == ("frontend-service",)
    assert "CLIENT001" in _ids(report)


def test_deterministic(tmp_path: Path) -> None:
    files = {"c/u.py": PY_BASIC, "w/a.ts": 'fetch("/pets/1")\n'}
    one = _clients(tmp_path / "a", files)
    two = _clients(tmp_path / "b", files)
    assert [s.to_dict() for s in one.call_sites] == [
        s.to_dict() for s in two.call_sites
    ]
