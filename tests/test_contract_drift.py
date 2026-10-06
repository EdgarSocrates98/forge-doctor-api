"""ApiContractDrift tests (spec 007, §14, §143-§146, §181-§182).

Both sides must always surface: spec-without-implementation and
implementation-without-spec fixtures are first-class cases, not absences.
"""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.routes.fastapi import FastApiAdapter
from forge_doctor_api.checks.drift import (
    ContractAuthority,
    contract_drift,
    normalize_path,
)
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.export import export_findings

HEADER = 'openapi: "3.0.3"\ninfo: {title: T, version: "1.0"}\n'

PYAPP = '''
from fastapi import FastAPI

app = FastAPI()
'''


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _report(root, spec_files, py_files, authority=ContractAuthority.UNDECLARED):
    _write(root, {**spec_files, **py_files})
    ctx = ProjectContext.from_root(root)
    model = load_openapi_project(ctx, list(spec_files))
    scan = FastApiAdapter().scan(ctx, "svc", list(py_files))
    return contract_drift(model, scan, authority)


def _ids(findings) -> list[str]:
    return [f.id for f in findings]


# -- identity + normalization ---------------------------------------------------


def test_normalize_path_conservative() -> None:
    assert normalize_path("/users/{id}/") == "/users/{}"
    assert normalize_path("/users/{userId}") == "/users/{}"
    assert normalize_path("/users/") == "/users"


def test_exact_match_clean(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets:\n    get:\n      operationId: listPets\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {"main.py": PYAPP + '@app.get("/pets")\ndef listPets(): ...\n'}
    report = _report(tmp_path, spec, py)
    assert report.findings == ()
    assert report.matched[0].matched_by == "path"


def test_operationid_correlation(tmp_path: Path) -> None:
    """FastAPI operationId defaults to the function name — correlate it."""
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets:\n    get:\n      operationId: listPets\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {"main.py": PYAPP + '@app.get("/pets")\ndef listPets(): ...\n'}
    report = _report(tmp_path, spec, py)
    assert report.findings == ()
    assert report.matched


# -- DRIFT001 / DRIFT002 / DRIFT010 -----------------------------------------------


def test_documented_missing_implementation(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets:\n    get:\n      operationId: listPets\n'
        + '      responses: {"200": {description: ok}}\n'
        + '  /owners:\n    get:\n      operationId: owners\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {"main.py": PYAPP + '@app.get("/pets")\ndef listPets(): ...\n'}
    report = _report(tmp_path, spec, py, ContractAuthority.OPENAPI)
    assert "DRIFT001" in _ids(report.findings)
    assert "operation:openapi:" in report.findings[0].entity_ids[0]


def test_implemented_absent_from_contract(tmp_path: Path) -> None:
    spec = {"api.yaml": HEADER + "paths: {}\n"}
    py = {"main.py": PYAPP + '@app.get("/pets")\ndef listPets(): ...\n'}
    report = _report(tmp_path, spec, py)
    assert "DRIFT002" in _ids(report.findings)


def test_undeclared_authority_reports_conflict_with_unknown(tmp_path: Path) -> None:
    spec = {"api.yaml": HEADER + "paths: {}\n"}
    py = {"main.py": PYAPP + '@app.get("/pets")\ndef listPets(): ...\n'}
    report = _report(tmp_path, spec, py, ContractAuthority.UNDECLARED)
    finding = next(f for f in report.findings if f.id == "DRIFT002")
    assert finding.unknowns, "undeclared authority must surface UnknownFact"


def test_openapi_authority_severity(tmp_path: Path) -> None:
    spec = {"api.yaml": HEADER + "paths: {}\n"}
    py = {"main.py": PYAPP + '@app.post("/pets")\ndef createPet(): ...\n'}
    openapi_auth = _report(tmp_path, spec, py, ContractAuthority.OPENAPI)
    impl_auth = _report(tmp_path, spec, py, ContractAuthority.IMPLEMENTATION)
    drift2_openapi = next(f for f in openapi_auth.findings if f.id == "DRIFT002")
    drift2_impl = next(f for f in impl_auth.findings if f.id == "DRIFT002")
    assert drift2_openapi.severity != drift2_impl.severity


def test_write_method_unmatched_is_breaking(tmp_path: Path) -> None:
    spec = {"api.yaml": HEADER + "paths: {}\n"}
    py = {"main.py": PYAPP + '@app.post("/pets")\ndef createPet(): ...\n'}
    report = _report(tmp_path, spec, py)
    ids = _ids(report.findings)
    assert "DRIFT002" in ids and "DRIFT010" in ids


def test_get_unmatched_not_breaking(tmp_path: Path) -> None:
    spec = {"api.yaml": HEADER + "paths: {}\n"}
    py = {"main.py": PYAPP + '@app.get("/pets")\ndef listPets(): ...\n'}
    report = _report(tmp_path, spec, py)
    ids = _ids(report.findings)
    assert "DRIFT002" in ids and "DRIFT010" not in ids


# -- DRIFT003 method mismatch ------------------------------------------------------


def test_method_mismatch(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets:\n    get:\n      operationId: listPets\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {"main.py": PYAPP + '@app.post("/pets")\ndef createPet(): ...\n'}
    report = _report(tmp_path, spec, py)
    ids = _ids(report.findings)
    assert "DRIFT003" in ids
    # both directions surface, no silent drop
    assert report.unmatched_operations and report.unmatched_routes


# -- DRIFT004 parameter mismatch ----------------------------------------------------


def test_param_name_drift(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /users/{id}:\n    get:\n      operationId: getUser\n      parameters:\n'
        + '        - {name: id, in: path, required: true}\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {
        "main.py": PYAPP + '@app.get("/users/{userId}")\ndef getUser(userId: int): ...\n'
    }
    report = _report(tmp_path, spec, py)
    ids = _ids(report.findings)
    assert "DRIFT004" in ids
    # structurally equal path still matched — §182 records, does not drop
    assert report.matched


def test_param_required_drift(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /users/{id}:\n    get:\n      operationId: getUser\n      parameters:\n'
        + '        - {name: id, in: path, required: true}\n'
        + '        - {name: q, in: query, required: true}\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {
        "main.py": PYAPP + '@app.get("/users/{id}")\ndef getUser(id: int, q: str = ""): ...\n'
    }
    report = _report(tmp_path, spec, py)
    assert "DRIFT004" in _ids(report.findings)


def test_param_missing_in_impl(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /users/{id}:\n    get:\n      operationId: getUser\n      parameters:\n'
        + '        - {name: id, in: path, required: true}\n'
        + '        - {name: org, in: query, required: true}\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {"main.py": PYAPP + '@app.get("/users/{id}")\ndef getUser(id: int): ...\n'}
    report = _report(tmp_path, spec, py)
    assert "DRIFT004" in _ids(report.findings)


def test_param_extra_in_impl(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /users/{id}:\n    get:\n      operationId: getUser\n      parameters:\n'
        + '        - {name: id, in: path, required: true}\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {
        "main.py": PYAPP
        + '@app.get("/users/{id}")\n'
        + 'def getUser(id: int, debug: bool = False): ...\n'
    }
    report = _report(tmp_path, spec, py)
    assert "DRIFT004" in _ids(report.findings)


def test_framework_param_not_a_drift(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /a:\n    get:\n      operationId: a\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {
        "main.py": PYAPP
        + 'from fastapi import Request\n\n\n@app.get("/a")\ndef a(request: Request): ...\n'
    }
    report = _report(tmp_path, spec, py)
    assert "DRIFT004" not in _ids(report.findings)


# -- DRIFT005/006 schema drift -------------------------------------------------------


def test_request_schema_missing_impl(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets:\n    post:\n      operationId: createPet\n'
        + '      requestBody:\n        content:\n          application/json:\n'
        + '            schema: {$ref: "#/components/schemas/Pet"}\n'
        + '      responses: {"200": {description: ok}}\n'
        + 'components:\n  schemas:\n    Pet: {type: object}\n'
    }
    py = {"main.py": PYAPP + '@app.post("/pets")\ndef createPet(): ...\n'}
    report = _report(tmp_path, spec, py)
    assert "DRIFT005" in _ids(report.findings)


def test_request_schema_name_mismatch(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets:\n    post:\n      operationId: createPet\n'
        + '      requestBody:\n        content:\n          application/json:\n'
        + '            schema: {$ref: "#/components/schemas/PetIn"}\n'
        + '      responses: {"200": {description: ok}}\n'
        + 'components:\n  schemas:\n    PetIn: {type: object}\n'
    }
    py = {
        "main.py": PYAPP
        + """
from pydantic import BaseModel


class Animal(BaseModel): ...


@app.post("/pets")
def createPet(body: Animal): ...
"""
    }
    report = _report(tmp_path, spec, py)
    assert "DRIFT005" in _ids(report.findings)


def test_request_schema_match_clean(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets:\n    post:\n      operationId: createPet\n'
        + '      requestBody:\n        content:\n          application/json:\n'
        + '            schema: {$ref: "#/components/schemas/Pet"}\n'
        + '      responses: {"200": {description: ok}}\n'
        + 'components:\n  schemas:\n    Pet: {type: object}\n'
    }
    py = {
        "main.py": PYAPP
        + """
from pydantic import BaseModel


class Pet(BaseModel): ...


@app.post("/pets")
def createPet(body: Pet): ...
"""
    }
    report = _report(tmp_path, spec, py)
    assert "DRIFT005" not in _ids(report.findings)


def test_response_schema_mismatch(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets:\n    get:\n      operationId: getPet\n      responses:\n'
        + '        "200":\n          description: ok\n          content:\n'
        + '            application/json:\n'
        + '              schema: {$ref: "#/components/schemas/Pet"}\n'
        + 'components:\n  schemas:\n    Pet: {type: object}\n'
    }
    py = {
        "main.py": PYAPP
        + """
from pydantic import BaseModel


class Animal(BaseModel): ...


@app.get("/pets", response_model=Animal)
def getPet(): ...
"""
    }
    report = _report(tmp_path, spec, py)
    assert "DRIFT006" in _ids(report.findings)


# -- DRIFT007/008/009 ----------------------------------------------------------------


def test_status_code_drift(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets:\n    post:\n      operationId: createPet\n      responses:\n'
        + '        "200": {description: ok}\n'
    }
    py = {"main.py": PYAPP + '@app.post("/pets", status_code=201)\ndef createPet(): ...\n'}
    report = _report(tmp_path, spec, py)
    assert "DRIFT007" in _ids(report.findings)


def test_auth_drift_contract_requires_impl_missing(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'security:\n  - bearerAuth: []\n'
        + 'paths:\n  /pets:\n    get:\n      operationId: listPets\n'
        + '      responses: {"200": {description: ok}}\n'
        + 'components:\n  securitySchemes:\n    bearerAuth: {type: http, scheme: bearer}\n'
    }
    py = {"main.py": PYAPP + '@app.get("/pets")\ndef listPets(): ...\n'}
    report = _report(tmp_path, spec, py)
    assert "DRIFT008" in _ids(report.findings)


def test_auth_drift_impl_enforces_contract_silent(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets:\n    get:\n      operationId: listPets\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {
        "main.py": PYAPP
        + 'from fastapi import Security\n\n\n'
        + '@app.get("/pets")\ndef listPets(user=Security(current_user)): ...\n'
    }
    report = _report(tmp_path, spec, py)
    assert "DRIFT008" in _ids(report.findings)


def test_deprecated_still_implemented(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /old:\n    get:\n      operationId: old\n      deprecated: true\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {"main.py": PYAPP + '@app.get("/old")\ndef old(): ...\n'}
    report = _report(tmp_path, spec, py)
    assert "DRIFT009" in _ids(report.findings)


# -- ApiErrorModel + report integrity ---------------------------------------------------


def test_error_model_populated(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets:\n    get:\n      operationId: listPets\n      responses:\n'
        + '        "200": {description: ok}\n'
        + '        "404": {description: nf, content: {application/json:\n'
        + '          {schema: {$ref: "#/components/schemas/Error"}}}}\n'
        + 'components:\n  schemas:\n    Error: {type: object}\n'
    }
    py = {"main.py": PYAPP + '@app.get("/pets")\ndef listPets(): ...\n'}
    report = _report(tmp_path, spec, py)
    em = report.error_model
    assert "404" in em.contract_error_statuses
    assert em.contract_error_shapes
    assert not em.impl_error_shapes_known
    assert em.unknowns


def test_both_sides_surfaced_no_silent_drops(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /contract-only:\n    get:\n      operationId: c\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {"main.py": PYAPP + '@app.get("/impl-only")\ndef i(): ...\n'}
    report = _report(tmp_path, spec, py)
    assert report.unmatched_operations
    assert report.unmatched_routes
    assert "DRIFT001" in _ids(report.findings)
    assert "DRIFT002" in _ids(report.findings)


# -- determinism -----------------------------------------------------------------------


def test_deterministic(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets/{id}:\n    get:\n      operationId: getPet\n      parameters:\n'
        + '        - {name: id, in: path, required: true}\n'
        + '      responses: {"200": {description: ok}}\n'
        + '  /orphan:\n    post:\n      operationId: orphan\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {
        "main.py": PYAPP + '@app.get("/pets/{petId}")\ndef getPet(petId: int): ...\n'
        + '@app.post("/extra")\ndef extra(): ...\n'
    }
    one = export_findings(_report(tmp_path, spec, py).findings).to_json()
    two = export_findings(_report(tmp_path, spec, py).findings).to_json()
    assert one == two


def test_findings_carry_both_locations(tmp_path: Path) -> None:
    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets:\n    get:\n      operationId: getPets\n      deprecated: true\n'
        + '      responses: {"200": {description: ok}}\n'
    }
    py = {"main.py": PYAPP + '@app.get("/pets")\ndef getPets(): ...\n'}
    report = _report(tmp_path, spec, py)
    finding = next(f for f in report.findings if f.id == "DRIFT009")
    assert finding.source_location is not None
    assert finding.evidence[0].kind.value == "STATIC"
    assert len(finding.evidence) >= 1


# -- §15 contract graph ----------------------------------------------------------


def test_contract_graph_edges(tmp_path: Path) -> None:
    from forge_doctor_api.analyzers.openapi.graph import contract_graph

    spec = {
        "api.yaml": HEADER
        + 'paths:\n  /pets:\n    post:\n      operationId: createPet\n'
        + '      requestBody:\n        content:\n          application/json:\n'
        + '            schema: {$ref: "#/components/schemas/Pet"}\n'
        + '      responses:\n        "201":\n          description: ok\n'
        + '          content:\n            application/json:\n'
        + '              schema: {$ref: "#/components/schemas/Pet"}\n'
        + 'components:\n  schemas:\n    Pet: {type: object}\n'
    }
    _write(tmp_path, spec)
    model = load_openapi_project(ProjectContext.from_root(tmp_path), ["api.yaml"])
    graph = contract_graph(model)
    ids = {e.id for e in graph.entities()}
    op_id = "operation:openapi:operation_id:createPet"
    assert "api:openapi:api.yaml" in ids
    assert op_id in ids
    assert "schema:openapi:api.yaml#Pet" in ids
    edges = {(r.kind, r.source_id, r.target_id) for r in graph.relationships()}
    assert ("EXPOSES", "api:openapi:api.yaml", op_id) in edges
    assert ("ACCEPTS", op_id, "schema:openapi:api.yaml#Pet") in edges
    assert ("RETURNS", op_id, "schema:openapi:api.yaml#Pet") in edges
