"""Policy engine tests (spec 023, §105-§107, §186-§189, §218).

Positive: each §105/§188 rule template fires from YAML policy docs; org ->
repo inheritance resolves; exceptions suppress only when valid. Negative:
missing config -> zero findings; expired/unapproved exceptions ignored and
surfaced. Boundary: repo policy that widens an org rule without a valid
exception keeps the org policy and emits POLICY009.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.version.detect import detect_version_model
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Severity
from forge_doctor_api.policy import (
    RuleContext,
    evaluate_policies,
    load_policies,
    resolve_ownership,
)
from forge_doctor_api.reliability import load_reliability_model
from forge_doctor_api.security import load_security_model

TODAY = date(2026, 10, 3)

API = """openapi: "3.0.3"
info: {title: Shop, version: "1.0", x-owner: payments-team}
paths:
  /users/{id}:
    get:
      description: fetch a user
      responses: {'200': {description: ok}}
  /health:
    get:
      operationId: health
      responses: {'200': {description: ok}}
components:
  securitySchemes:
    apiKey: {type: apiKey, in: header, name: X-Key}
"""

POLICY_ORG = """level: organization
policies:
  - id: org.require_auth
    rule: require_auth
    severity: high
exceptions: []
"""

POLICY_REPO_OVERRIDE_WEAK = """level: repo
policies:
  - id: repo.require_auth
    rule: require_auth
    enabled: false
exceptions: []
"""

POLICY_REPO_OVERRIDE_OK = """level: repo
policies:
  - id: repo.require_auth
    rule: require_auth
    severity: critical
exceptions: []
"""

POLICY_ALL = """policies:
  - id: r.require_auth
    rule: require_auth
  - id: r.require_oid
    rule: require_operation_id
  - id: r.no_cors
    rule: no_wildcard_cors
  - id: r.owner
    rule: require_owner
  - id: r.docs
    rule: doc_coverage
  - id: r.deprecation
    rule: min_deprecation_days
    params: {min_days: 180}
exceptions: []
"""

CFG = """cors:
  scope: public
  allow_origins: "*"
"""

EXC_EXPIRED = """level: repo
policies:
  - id: r.auth
    rule: require_auth
exceptions:
  - rule: require_auth
    scope: "*"
    owner: team-a
    justification: sandbox
    created: "2025-01-01"
    expires: "2025-12-31"
    approval: approved
"""

EXC_PENDING = EXC_EXPIRED.replace('"2025-12-31"', '"2027-12-31"').replace(
    "approval: approved", "approval: pending"
)

EXC_VALID = EXC_EXPIRED.replace('"2025-12-31"', '"2027-12-31"')


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _ctx(root: Path) -> RuleContext:
    ctx = ProjectContext.from_root(root)
    files = list(ctx.iter_files())
    openapi = load_openapi_project(ctx)
    return RuleContext(
        openapi=openapi,
        security=load_security_model(ctx, files, openapi=openapi),
        reliability=load_reliability_model(ctx, files),
        version=detect_version_model(openapi),
        ownership=resolve_ownership(ctx, files, openapi),
    )


def _evaluate(root: Path):
    ctx = ProjectContext.from_root(root)
    policy_set = load_policies(ctx, list(ctx.iter_files()))
    return evaluate_policies(policy_set, _ctx(root), TODAY)


# -- rule templates -------------------------------------------------------------


def test_require_auth_and_operation_id(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {"api.yaml": API, "policies.yaml": POLICY_ALL})
    findings = _evaluate(root)
    auth = [f for f in findings if f.id == "POLICY001"]
    assert auth  # neither op has security
    assert any("users" in f.description for f in auth)
    oid = [f for f in findings if f.id == "POLICY005"]
    assert oid and "getUser" not in oid[0].description  # op without operationId


def test_wildcard_cors_violation(tmp_path: Path) -> None:
    root = _write(
        tmp_path / "p",
        {"api.yaml": API, "cfg.yaml": CFG, "policies.yaml": POLICY_ALL},
    )
    findings = _evaluate(root)
    assert any(f.id == "POLICY003" and "wildcard" in f.description.lower() for f in findings)


def test_owner_required(tmp_path: Path) -> None:
    # project has no owner sources
    root = _write(
        tmp_path / "p",
        {
            "api.yaml": API.replace(", x-owner: payments-team", ""),
            "policies.yaml": POLICY_ALL,
        },
    )
    findings = _evaluate(root)
    assert any(f.id == "POLICY006" for f in findings)


def test_doc_coverage_is_opportunity(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {"api.yaml": API, "policies.yaml": POLICY_ALL})
    findings = _evaluate(root)
    docs = [f for f in findings if f.id == "POLICY007"]
    assert docs and all(f.severity is Severity.INFO for f in docs)


def test_doc_coverage_schemas_and_error_docs(tmp_path: Path) -> None:
    api = """openapi: "3.0.3"
info: {title: Shop, version: "1.0"}
paths:
  /items:
    get:
      operationId: listItems
      description: documented
      responses:
        '200': {description: ok}
        '404': {}
components:
  schemas:
    Documented: {type: object, description: has docs}
    Bare: {type: object}
"""
    root = _write(tmp_path / "p", {"api.yaml": api, "policies.yaml": POLICY_ALL})
    docs = [f for f in _evaluate(root) if f.id == "POLICY007"]
    details = " ".join(f.description for f in docs)
    assert "Bare" in details  # undocumented schema flagged
    assert "Documented" not in details  # documented schema not flagged
    assert "404" in details  # error response without description flagged


def test_doc_coverage_deprecated_without_notes(tmp_path: Path) -> None:
    api = """openapi: "3.0.3"
info: {title: Shop, version: "1.0"}
paths:
  /old:
    get:
      operationId: oldOp
      deprecated: true
      responses: {'200': {description: ok}}
"""
    root = _write(tmp_path / "p", {"api.yaml": api, "policies.yaml": POLICY_ALL})
    docs = [f for f in _evaluate(root) if f.id == "POLICY007"]
    assert any("deprecated" in f.description for f in docs)


def test_no_policy_config_no_findings(tmp_path: Path) -> None:
    """Missing config must not invent org rules."""
    root = _write(tmp_path / "p", {"api.yaml": API})
    findings = _evaluate(root)
    assert findings == ()


# -- §106 inheritance -----------------------------------------------------------


def test_inheritance_closest_scope_wins(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {
        "api.yaml": API,
        "org.policy.yaml": POLICY_ORG,
        "repo.policy.yaml": POLICY_REPO_OVERRIDE_OK,
    })
    findings = _evaluate(root)
    auth = [f for f in findings if f.id == "POLICY001"]
    assert auth and all("[repo" in f.description for f in auth)
    assert all(f.severity is Severity.CRITICAL for f in auth)


def test_widening_without_exception_keeps_org_policy(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {
        "api.yaml": API,
        "org.policy.yaml": POLICY_ORG,
        "repo.policy.yaml": POLICY_REPO_OVERRIDE_WEAK,
    })
    findings = _evaluate(root)
    # repo tried to disable require_auth -> widening -> org policy kept + POLICY009
    assert any(f.id == "POLICY009" for f in findings)
    assert any(f.id == "POLICY001" for f in findings)  # org policy still fires


def test_widening_with_valid_exception_honored(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {
        "api.yaml": API,
        "org.policy.yaml": POLICY_ORG,
        "repo.policy.yaml": POLICY_REPO_OVERRIDE_WEAK.replace(
            "exceptions: []", """exceptions:
  - rule: require_auth
    scope: "*"
    owner: security-team
    justification: internal sandbox
    created: "2026-01-01"
    expires: "2027-01-01"
    approval: approved
"""),
    })
    findings = _evaluate(root)
    # exception valid -> repo disable honored -> no require_auth violations
    assert not any(f.id == "POLICY001" for f in findings)


# -- §107 exceptions ------------------------------------------------------------


def test_expired_exception_ignored_and_surfaced(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {"api.yaml": API, "policies.yaml": EXC_EXPIRED})
    findings = _evaluate(root)
    assert any(f.id == "POLICY008" and "expired" in f.description for f in findings)
    assert any(f.id == "POLICY001" for f in findings)  # violations still fire


def test_pending_exception_is_not_approval(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {"api.yaml": API, "policies.yaml": EXC_PENDING})
    findings = _evaluate(root)
    assert any(f.id == "POLICY008" and "not approved" in f.description for f in findings)


def test_valid_exception_suppresses(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {"api.yaml": API, "policies.yaml": EXC_VALID})
    findings = _evaluate(root)
    assert not any(f.id == "POLICY001" for f in findings)
    assert not any(f.id == "POLICY008" for f in findings)


def test_exception_missing_fields_is_issue(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {
        "api.yaml": API,
        "policies.yaml": """policies:
  - rule: require_auth
exceptions:
  - rule: require_auth
    scope: "*"
""",
    })
    findings = _evaluate(root)
    assert any(f.id == "POLICY010" and "missing fields" in f.description for f in findings)


# -- §186 ownership -------------------------------------------------------------


def test_ownership_precedence_openapi_beats_codeowners(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {
        "api.yaml": API,
        "CODEOWNERS": "* @platform-team\n",
        "catalog-info.yaml": "spec: {owner: catalog-team}\n",
    })
    ctx = ProjectContext.from_root(root)
    own = resolve_ownership(ctx, list(ctx.iter_files()), load_openapi_project(ctx))
    assert own[0].owner == "payments-team"  # x-owner extension wins
    sources = {s.source for s in own[0].sources}
    assert {"openapi_extension", "catalog", "codeowners"} <= sources
    assert own[0].precedence[0] == "openapi_extension"


def test_ownership_falls_back_to_codeowners(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {
        "api.yaml": API.replace(", x-owner: payments-team", ""),
        "CODEOWNERS": "* @platform-team\n",
    })
    ctx = ProjectContext.from_root(root)
    own = resolve_ownership(ctx, list(ctx.iter_files()), load_openapi_project(ctx))
    assert own[0].owner == "@platform-team"


def test_malformed_policy_file_is_finding(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {
        "api.yaml": API,
        "policies.yaml": "policies: [not, a, mapping\n",
    })
    findings = _evaluate(root)
    assert any(f.id == "POLICY010" for f in findings)


def test_deterministic_ordering(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {"api.yaml": API, "cfg.yaml": CFG,
                                  "policies.yaml": POLICY_ALL})
    a, b = _evaluate(root), _evaluate(root)
    assert [(f.id, f.description) for f in a] == [(f.id, f.description) for f in b]


def test_min_deprecation_days(tmp_path: Path) -> None:
    api = API.replace(
        'info: {title: Shop, version: "1.0", x-owner: payments-team}',
        'info: {title: Shop, version: "1.0", deprecated: true, '
        'x-deprecation-date: "2026-01-01", x-sunset-date: "2026-02-01"}',
    )
    root = _write(tmp_path / "p", {"api.yaml": api, "policies.yaml": POLICY_ALL})
    findings = _evaluate(root)
    assert any(f.id == "POLICY004" and "180" in f.description for f in findings)
