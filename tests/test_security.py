"""Security intelligence tests (spec 018, §48-57, §115-120, §229)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.checks.apisec import run_security_checks
from forge_doctor_api.checks.apisec.catalog import BY_ID
from forge_doctor_api.cli import app
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.security import (
    AuthSchemeType,
    PaginationKind,
    load_security_model,
)
from forge_doctor_api.security.knowledge import (
    check_to_owasp,
    owasp_categories,
)

HEADER = "openapi: 3.0.3\ninfo: {title: T, version: '1'}\n"


def _load(tmp_path: Path, files: dict[str, str], with_openapi=True):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    ctx = ProjectContext.from_root(tmp_path)
    oas = load_openapi_project(ctx) if with_openapi else None
    m = load_security_model(ctx, list(ctx.iter_files()), openapi=oas)
    return m, oas


def _ids(model, oas):
    return [f.id for f in run_security_checks(model, openapi=oas)]


# ---------- knowledge pack ----------


def test_owasp_pack_covers_ten_categories() -> None:
    cats = owasp_categories()
    assert len(cats) == 10
    assert cats["API1"] == "Broken Object Level Authorization"
    assert cats["API7"] == "Server Side Request Forgery"


def test_owasp_mapping_from_pack_not_code() -> None:
    assert check_to_owasp("APISEC001") == ("API1",)
    assert check_to_owasp("APISEC007") == ("API7",)
    assert check_to_owasp("APISEC999") == ()


# ---------- auth scheme model ----------


def test_auth_scheme_type_mapping(tmp_path: Path) -> None:
    m, _ = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths: {}\n"
            "components:\n  securitySchemes:\n"
            "    oauth: {type: oauth2, flows: {}}\n"
            "    oidc: {type: openIdConnect, openIdConnectUrl: u}\n"
            "    jwt: {type: http, scheme: bearer, bearerFormat: JWT}\n"
            "    key: {type: apiKey, in: header, name: X-Key}\n"
            "    basic: {type: http, scheme: basic}\n"
            "    mtls: {type: mutualTLS}\n"
        ),
    })
    kinds = {s.name: s.type for s in m.auth_schemes}
    assert kinds["oauth"] is AuthSchemeType.OAUTH2
    assert kinds["oidc"] is AuthSchemeType.OIDC
    assert kinds["jwt"] is AuthSchemeType.JWT
    assert kinds["key"] is AuthSchemeType.API_KEY
    assert kinds["basic"] is AuthSchemeType.BASIC
    assert kinds["mtls"] is AuthSchemeType.MTLS


def test_authz_policy_from_extensions_and_scopes(tmp_path: Path) -> None:
    m, _ = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /accounts/{account_id}:\n    get:\n"
            "      operationId: getAccount\n"
            "      x-roles: [owner, admin]\n"
            "      x-ownership-check: true\n"
            "      security:\n        - oauth: [read:accounts]\n"
            "      responses: {'200': {description: ok}}\n"
            "components:\n  securitySchemes:\n"
            "    oauth: {type: oauth2, flows: {}}\n"
        ),
    })
    pol = next(p for p in m.authorization if "getAccount" in p.operation)
    assert set(pol.roles) == {"owner", "admin"}
    assert "read:accounts" in pol.scopes
    assert pol.ownership_check is True


# ---------- APISEC001 - BOLA candidate (demo §229) ----------


def test_apisec001_bola_candidate(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /users/{user_id}:\n    get:\n"
            "      operationId: getUser\n      security: []\n"
            "      parameters:\n        - name: user_id\n"
            "          in: path\n          required: true\n"
            "          schema: {type: integer}\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    f = next(f for f in run_security_checks(m, openapi=oas)
             if f.id == "APISEC001")
    assert "BOLA risk candidate" in f.description
    assert "confirmed" not in f.description
    assert f.unknowns


def test_apisec001_silent_with_ownership_check(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /users/{user_id}:\n    get:\n"
            "      operationId: getUser\n      x-ownership-check: true\n"
            "      parameters:\n        - name: user_id\n"
            "          in: path\n          required: true\n"
            "          schema: {type: integer}\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    assert "APISEC001" not in _ids(m, oas)


def test_apisec001_silent_on_non_id_params(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /search/{query}:\n    get:\n"
            "      operationId: search\n      security: []\n"
            "      parameters:\n        - name: query\n"
            "          in: path\n          required: true\n"
            "          schema: {type: string}\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    assert "APISEC001" not in _ids(m, oas)


# ---------- APISEC002/003 ----------


def test_apisec002_admin_without_authz(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /admin/users:\n    delete:\n"
            "      operationId: deleteAllUsers\n"
            "      responses: {'204': {description: ok}}\n"
        ),
    })
    assert "APISEC002" in _ids(m, oas)


def test_apisec002_silent_with_roles(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /admin/users:\n    delete:\n"
            "      operationId: deleteAllUsers\n      x-roles: [admin]\n"
            "      responses: {'204': {description: ok}}\n"
        ),
    })
    assert "APISEC002" not in _ids(m, oas)


def test_apisec003_anonymous_sensitive(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /health-records:\n    get:\n"
            "      operationId: getRecords\n      security: []\n"
            "      x-data-classification: health\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    assert "APISEC003" in _ids(m, oas)


def test_apisec003_no_name_inference(tmp_path: Path) -> None:
    # `password` in the path must NOT imply sensitivity (§124)
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /passwords:\n    get:\n"
            "      operationId: listPasswords\n      security: []\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    assert "APISEC003" not in _ids(m, oas)


# ---------- APISEC004/005/006 ----------


def test_apisec004_wildcard_cors(tmp_path: Path) -> None:
    m, _ = _load(tmp_path, {
        "gw.yaml": (
            "cors:\n  scope: gw\n  allowed_origins: ['*']\n"
            "  allow_credentials: true\n"
        ),
    }, with_openapi=False)
    f = next(f for f in run_security_checks(m) if f.id == "APISEC004")
    assert "credentials" in f.description


def test_apisec004_python_cors_middleware(tmp_path: Path) -> None:
    m, _ = _load(tmp_path, {
        "app.py": (
            "from fastapi.middleware.cors import CORSMiddleware\n"
            "app.add_middleware(CORSMiddleware, allow_origins=['*'],"
            " allow_credentials=True)\n"
        ),
    }, with_openapi=False)
    assert m.cors and m.cors[0].wildcard


def test_apisec005_public_op_no_rate_limit(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /public/ping:\n    get:\n"
            "      operationId: ping\n      security: []\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    assert "APISEC005" in _ids(m, oas)


def test_apisec005_silent_when_covered(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /public/ping:\n    get:\n"
            "      operationId: ping\n      security: []\n"
            "      responses: {'200': {description: ok}}\n"
        ),
        "gw.yaml": "rate_limit:\n  scope: '*'\n  limit: 100\n  window: 1m\n",
    })
    assert "APISEC005" not in _ids(m, oas)


def test_apisec006_unbounded_list(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /users:\n    get:\n      operationId: listUsers\n"
            "      responses: {'200': {description: ok, content:"
            " {application/json: {schema: {type: array,"
            " items: {type: string}}}}}}\n"
        ),
    })
    assert "APISEC006" in _ids(m, oas)


def test_apisec006_silent_with_pagination(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /users:\n    get:\n      operationId: listUsers\n"
            "      parameters:\n        - name: limit\n"
            "          in: query\n          schema: {type: integer}\n"
            "      responses: {'200': {description: ok, content:"
            " {application/json: {schema: {type: array,"
            " items: {type: string}}}}}}\n"
        ),
    })
    assert "APISEC006" not in _ids(m, oas)


def test_apisec006_silent_for_singleton(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /admin/panel:\n    get:\n"
            "      operationId: panel\n"
            "      responses: {'200': {description: ok, content:"
            " {application/json: {schema: {type: object}}}}}\n"
        ),
    })
    assert "APISEC006" not in _ids(m, oas)


def test_pagination_kinds(tmp_path: Path) -> None:
    m, _ = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n"
            "  /a:\n    get:\n      operationId: a\n"
            "      parameters:\n        - {name: cursor, in: query}\n"
            "      responses: {'200': {description: ok}}\n"
            "  /b:\n    get:\n      operationId: b\n"
            "      parameters:\n        - {name: offset, in: query}\n"
            "        - {name: limit, in: query}\n"
            "      responses: {'200': {description: ok}}\n"
            "  /c:\n    get:\n      operationId: c\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    kinds = {p.operation: p.kind for p in m.pagination}
    assert kinds["operation_id:a"] is PaginationKind.CURSOR
    assert kinds["operation_id:b"] is PaginationKind.OFFSET
    assert kinds["operation_id:c"] is PaginationKind.NONE


# ---------- APISEC007/008/009/010 ----------


def test_apisec007_url_param(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /fetch:\n    post:\n      operationId: fetchIt\n"
            "      parameters:\n        - {name: url, in: query}\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    assert "APISEC007" in _ids(m, oas)


def test_apisec007_silent_without_url_params(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /items/{item_id}:\n    get:\n"
            "      operationId: getItem\n      x-ownership-check: true\n"
            "      parameters:\n        - {name: item_id, in: path}\n"
            "        - {name: format, in: query}\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    assert "APISEC007" not in _ids(m, oas)


def test_apisec008_classified_property_in_response(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /users/{user_id}:\n    get:\n"
            "      operationId: getUser\n      x-ownership-check: true\n"
            "      parameters:\n        - {name: user_id, in: path}\n"
            "      responses: {'200': {description: ok, content:"
            " {application/json: {schema:"
            " {$ref: '#/components/schemas/User'}}}}}\n"
            "components:\n  schemas:\n    User:\n      type: object\n"
            "      properties:\n        id: {type: integer}\n"
            "        ssn: {type: string, x-pii: true}\n"
        ),
    })
    f = [f for f in run_security_checks(m, openapi=oas)
         if f.id == "APISEC008"]
    assert f and "User.ssn" in f[0].description
    # single deduplicated classification record
    assert len(m.classifications) == 1


def test_apisec008_silent_when_not_in_response(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /users/{user_id}:\n    get:\n"
            "      operationId: getUser\n      x-ownership-check: true\n"
            "      parameters:\n        - {name: user_id, in: path}\n"
            "      responses: {'200': {description: ok}}\n"
            "components:\n  schemas:\n    User:\n      type: object\n"
            "      properties:\n        ssn: {type: string, x-pii: true}\n"
        ),
    })
    assert "APISEC008" not in _ids(m, oas)


def test_apisec009_deprecated_reachable(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /old:\n    get:\n      operationId: oldOp\n"
            "      deprecated: true\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    assert "APISEC009" in _ids(m, oas)


def test_apisec010_external_api_gaps(tmp_path: Path) -> None:
    m, _ = _load(tmp_path, {
        "deps.yaml": (
            "external_apis:\n  - host: api.stripe.example\n"
            "    owner: payments\n"
            "  - host: api.ok.example\n    timeout: 5000\n    auth: api-key\n"
        ),
    }, with_openapi=False)
    findings = [f for f in run_security_checks(m) if f.id == "APISEC010"]
    assert len(findings) == 1
    assert "api.stripe.example" in findings[0].description


# ---------- webhooks / flows / tls / drift ----------


def test_webhook_model_from_config(tmp_path: Path) -> None:
    m, _ = _load(tmp_path, {
        "hooks.yaml": (
            "webhooks:\n  - name: order-placed\n    signature: hmac\n"
            "    retry: true\n"
        ),
    }, with_openapi=False)
    wh = m.webhooks[0]
    assert wh.name == "order-placed"
    assert wh.signature_verification is True
    assert wh.retry is True
    assert wh.replay_protection is None  # absent stays None, not False


def test_business_flow_declared_only(tmp_path: Path) -> None:
    m, _ = _load(tmp_path, {
        "flows.yaml": (
            "business_flows:\n  - name: checkout\n"
            "    protections: [rate-limit, captcha]\n"
        ),
    }, with_openapi=False)
    assert m.business_flows[0].name == "checkout"


def test_tls_evidence_config_only(tmp_path: Path) -> None:
    m, _ = _load(tmp_path, {
        "deploy.yaml": "tls:\n  scope: edge\nmtls:\n  scope: internal\n",
    }, with_openapi=False)
    kinds = {t.kind for t in m.tls}
    assert {"tls", "mtls"} <= kinds


def test_auth_drift_contract_vs_impl(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text(HEADER + (
        "paths:\n  /users/{user_id}:\n    get:\n"
        "      operationId: getUser\n"
        "      security:\n        - oauth: []\n"
        "      parameters:\n        - {name: user_id, in: path}\n"
        "      responses: {'200': {description: ok}}\n"
        "components:\n  securitySchemes:\n"
        "    oauth: {type: oauth2, flows: {}}\n"
    ))
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "@app.get('/users/{user_id}')\ndef getUser(user_id: int):\n"
        "    pass\n"
    )
    ctx = ProjectContext.from_root(tmp_path)
    from forge_doctor_api.analyzers.routes import FastApiAdapter
    oas = load_openapi_project(ctx)
    scan = FastApiAdapter().scan(ctx, "svc")
    m = load_security_model(ctx, list(ctx.iter_files()),
                            openapi=oas, routes=scan)
    assert m.auth_drift
    d = m.auth_drift[0]
    assert d.contract_secured is True
    assert d.impl_secured is False


def test_no_drift_when_aligned(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text(HEADER + (
        "paths:\n  /users/{user_id}:\n    get:\n"
        "      operationId: getUser\n"
        "      security:\n        - oauth: []\n"
        "      parameters:\n        - {name: user_id, in: path}\n"
        "      responses: {'200': {description: ok}}\n"
        "components:\n  securitySchemes:\n"
        "    oauth: {type: oauth2, flows: {}}\n"
    ))
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI, Security\napp = FastAPI()\n"
        "@app.get('/users/{user_id}')\ndef getUser(user_id: int,"
        " u=Security(check)):\n    pass\n"
    )
    ctx = ProjectContext.from_root(tmp_path)
    from forge_doctor_api.analyzers.routes import FastApiAdapter
    oas = load_openapi_project(ctx)
    scan = FastApiAdapter().scan(ctx, "svc")
    m = load_security_model(ctx, list(ctx.iter_files()),
                            openapi=oas, routes=scan)
    assert not m.auth_drift


# ---------- redaction (§57/§125) ----------


def test_no_secret_leakage_in_findings(tmp_path: Path) -> None:
    secret = "sk-live-abcdef1234567890"
    m, oas = _load(tmp_path, {
        "deps.yaml": (
            "external_apis:\n  - host: api.x.example\n"
            f"    api_key: {secret}\n"
        ),
        "openapi.yaml": HEADER + (
            "paths:\n  /users/{user_id}:\n    get:\n"
            "      operationId: getUser\n      security: []\n"
            "      parameters:\n        - {name: user_id, in: path}\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    from forge_doctor_api.core.export import export_findings
    findings = run_security_checks(m, openapi=oas)
    payload = json.dumps(export_findings(findings).to_dict())
    model_payload = json.dumps(m.to_dict())
    assert secret not in payload
    assert secret not in model_payload


# ---------- demo §229 + CLI ----------


def test_demo_229(tmp_path: Path) -> None:
    _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /users/{user_id}:\n    get:\n"
            "      operationId: getUser\n      security: []\n"
            "      parameters:\n        - {name: user_id, in: path,"
            " required: true, schema: {type: integer}}\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    r = CliRunner().invoke(
        app, ["security", "inspect", str(tmp_path), "--json"])
    assert r.exit_code == 0
    payload = json.loads(r.output)
    descs = " ".join(f["description"] for f in payload["findings"]["findings"])
    assert "BOLA risk candidate" in descs
    assert "vulnerability confirmed" not in descs


def test_security_inspect_json(tmp_path: Path) -> None:
    _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /users/{user_id}:\n    get:\n"
            "      operationId: getUser\n      security: []\n"
            "      parameters:\n        - {name: user_id, in: path}\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    r = CliRunner().invoke(
        app, ["security", "inspect", str(tmp_path), "--json"])
    assert r.exit_code == 0
    payload = json.loads(r.output)
    assert payload["findings"]["findings"]


def test_empty_project_no_findings(tmp_path: Path) -> None:
    (tmp_path / "readme.yaml").write_text("title: nothing\n")
    ctx = ProjectContext.from_root(tmp_path)
    m = load_security_model(ctx, list(ctx.iter_files()))
    assert run_security_checks(m) == ()


def test_never_confirmed_language(tmp_path: Path) -> None:
    m, oas = _load(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /users/{user_id}:\n    get:\n"
            "      operationId: getUser\n      security: []\n"
            "      parameters:\n        - {name: user_id, in: path}\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    for f in run_security_checks(m, openapi=oas):
        d = f.description.lower()
        assert "confirmed" not in d
        assert "[candidate]" in f.description \
            or "[configuration risk]" in f.description


def test_catalog_ids_match_owasp_pack() -> None:
    for check_id in BY_ID:
        assert check_to_owasp(check_id), check_id


def test_determinism(tmp_path: Path) -> None:
    files = {
        "openapi.yaml": HEADER + (
            "paths:\n  /users/{user_id}:\n    get:\n"
            "      operationId: getUser\n      security: []\n"
            "      parameters:\n        - {name: user_id, in: path}\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    }
    m1, o1 = _load(tmp_path / "a", files)
    m2, o2 = _load(tmp_path / "b", files)
    d1 = [f.description for f in run_security_checks(m1, openapi=o1)]
    d2 = [f.description for f in run_security_checks(m2, openapi=o2)]
    assert d1 == d2


# ---------- spec 061: auth-coverage chain + sensitive fields ----------

def _sec(tmp_path: Path, doc: str):
    return _load(tmp_path, {"o.yaml": HEADER + doc})


def test_global_auth_inherited_no_011(tmp_path: Path) -> None:
    """Op inheriting global security must not false-positive."""
    m, oas = _sec(tmp_path, """
paths:
  /a:
    get:
      operationId: a
      responses: {'200': {description: ok}}
components:
  securitySchemes:
    b: {type: http, scheme: bearer}
security:
  - b: []
""")
    ids = [f.id for f in run_security_checks(m, openapi=oas)]
    assert "APISEC011" not in ids


def test_ambiguous_override_is_unknown(tmp_path: Path) -> None:
    """Op declaring security that resolves to no requirement while a
    global requirement exists -> UNKNOWN, never PASS/FAIL."""
    m, oas = _sec(tmp_path, """
paths:
  /a:
    get:
      operationId: a
      security:
        - ghost: []
      responses: {'200': {description: ok}}
components:
  securitySchemes:
    b: {type: http, scheme: bearer}
security:
  - b: []
""")
    findings = run_security_checks(m, openapi=oas)
    f = next((f for f in findings if f.id == "APISEC011"), None)
    assert f is not None
    assert f.unknowns, "ambiguous override must carry UnknownFact"


def test_no_security_anywhere_is_011(tmp_path: Path) -> None:
    m, oas = _sec(tmp_path, """
paths:
  /a:
    get: {operationId: a, responses: {'200': {description: ok}}}
""")
    ids = [f.id for f in run_security_checks(m, openapi=oas)]
    assert "APISEC011" in ids


def test_sensitive_field_candidate(tmp_path: Path) -> None:
    m, oas = _sec(tmp_path, """
paths:
  /a:
    get: {operationId: a, responses: {'200': {description: ok}}}
components:
  schemas:
    User:
      type: object
      properties:
        name: {type: string}
        password: {type: string}
  securitySchemes:
    b: {type: http, scheme: bearer}
security:
  - b: []
""")
    findings = run_security_checks(m, openapi=oas)
    f = next((f for f in findings if f.id == "APISEC012"), None)
    assert f is not None
    assert "password" in f.description
    assert f.confidence.value == "LOW"


def test_declared_redaction_suppresses_012(tmp_path: Path) -> None:
    m, oas = _sec(tmp_path, """
paths:
  /a:
    get: {operationId: a, responses: {'200': {description: ok}}}
components:
  schemas:
    User:
      type: object
      properties:
        password: {type: string, writeOnly: true}
  securitySchemes:
    b: {type: http, scheme: bearer}
security:
  - b: []
""")
    ids = [f.id for f in run_security_checks(m, openapi=oas)]
    assert "APISEC012" not in ids


def test_format_password_suppresses_012(tmp_path: Path) -> None:
    m, oas = _sec(tmp_path, """
paths:
  /a:
    get: {operationId: a, responses: {'200': {description: ok}}}
components:
  schemas:
    User:
      type: object
      properties:
        password: {type: string, format: password}
  securitySchemes:
    b: {type: http, scheme: bearer}
security:
  - b: []
""")
    ids = [f.id for f in run_security_checks(m, openapi=oas)]
    assert "APISEC012" not in ids
