"""OAS### check suite tests (spec 005).

Layout:
- `PRECISION` is the precision harness: each case declares the findings that
  must fire (`expect`, as check-id -> minimum count) and the check ids that
  must NOT fire (`forbid`). Cases are positive, negative, malformed, and
  adversarial fixtures per §199-202's low-false-positive bar.
- Focused tests assert finding content (severity/confidence/unknowns/
  entity ids/locations) and versioned export round-trips.
- Determinism tests hash the export twice and over shuffled input order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.checks.oas import CATALOG, run_openapi_checks
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.export import export_findings
from forge_doctor_api.core.models import Confidence, EvidenceKind, Finding, Severity

HEADER = 'openapi: "3.0.3"\ninfo: {title: T, version: "1.0"}\n'


@dataclass(frozen=True)
class Case:
    name: str
    files: dict[str, str]
    expect: dict[str, int] = field(default_factory=dict)
    forbid: frozenset[str] = frozenset()
    paths: tuple[str, ...] | None = None


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _run(root: Path, case: Case) -> tuple[Finding, ...]:
    _write(root, case.files)
    model = load_openapi_project(
        ProjectContext.from_root(root), list(case.paths) if case.paths else None
    )
    return run_openapi_checks(model)


def _spec(path: str, body: str) -> dict[str, str]:
    return {"api.yaml": HEADER + body}


PRECISION: tuple[Case, ...] = (
    # -- OAS001: invalid spec version ----------------------------------------
    Case(
        name="unsupported-version",
        files={"api.yaml": 'openapi: "4.0.0"\ninfo: {title: T, version: "1"}\npaths: {}\n'},
        expect={"OAS001": 1},
        forbid=frozenset({"OAS002", "OAS003", "OAS004"}),
    ),
    Case(
        name="swagger-2-adversarial",
        files={"api.yaml": 'swagger: "2.0"\ninfo: {title: T, version: "1"}\npaths: {}\n'},
        expect={"OAS001": 1},
    ),
    Case(
        name="malformed-yaml",
        files={"api.yaml": 'openapi: "3.1.0"\npaths: {\n  bad'},
        expect={"OAS001": 1},
        forbid=frozenset({"OAS005", "OAS010"}),
    ),
    Case(
        name="not-openapi-random-yaml",
        files={"api.yaml": "paths: {}\ninfo: {}\n"},
        forbid=frozenset({spec.id for spec in CATALOG}),
    ),
    Case(
        name="not-openapi-named-file",
        files={"openapi.yml": "database:\n  host: x\n  ports: [1, 2]\n"},
        forbid=frozenset({spec.id for spec in CATALOG}),
    ),
    Case(
        name="version-not-semver",
        files={"api.yaml": 'openapi: "3.1"\ninfo: {}\n'},
        expect={"OAS001": 1},
    ),
    # -- OAS002: unresolved local ref -----------------------------------------
    Case(
        name="missing-local-ref",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      responses:\n        "200":\n'
            "          $ref: '#/components/responses/Nope'\n",
        ),
        expect={"OAS002": 1},
        forbid=frozenset({"OAS005"}),  # unresolved ref: description is UNKNOWN, not missing
    ),
    Case(
        name="missing-file-ref",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      responses:\n        "200":\n'
            "          $ref: 'gone.yaml#/components/responses/Ok'\n",
        ),
        expect={"OAS002": 1},
    ),
    Case(
        name="external-ref-never-reported",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      responses:\n        "200":\n'
            "          description: ok\n          content:\n            application/json:\n"
            "              schema:\n                $ref: 'https://example.com/x.json#/S'\n",
        ),
        forbid=frozenset({"OAS002"}),
    ),
    # -- OAS003: duplicate operationId ----------------------------------------
    Case(
        name="dup-operationid-single-file",
        files=_spec(
            "",
            'paths:\n  /a:\n    get: {operationId: dup, responses: {"200": {description: ok}}}\n'
            '  /b:\n    get: {operationId: dup, responses: {"200": {description: ok}}}\n',
        ),
        expect={"OAS003": 1},
    ),
    Case(
        name="dup-operationid-multi-file",
        files={
            "a.yaml": HEADER
            + 'paths:\n  /a:\n    get:\n      operationId: shared\n'
            + '      responses: {"200": {description: ok}}\n',
            "b.yaml": HEADER
            + 'paths:\n  /b:\n    post:\n      operationId: shared\n'
            + '      responses: {"200": {description: ok}}\n',
        },
        expect={"OAS003": 1},
        paths=("a.yaml", "b.yaml"),
    ),
    Case(
        name="unique-operationids",
        files=_spec(
            "",
            'paths:\n  /a:\n    get: {operationId: a1, responses: {"200": {description: ok}}}\n'
            '  /b:\n    get: {operationId: b1, responses: {"200": {description: ok}}}\n',
        ),
        forbid=frozenset({"OAS003", "OAS004"}),
    ),
    # -- OAS004: missing operationId ------------------------------------------
    Case(
        name="missing-operationid",
        files=_spec(
            "", 'paths:\n  /a:\n    get:\n      responses: {"200": {description: ok}}\n'
        ),
        expect={"OAS004": 1},
    ),
    Case(
        name="webhook-operationid-exempt",
        files=_spec(
            "",
            'paths: {}\nwebhooks:\n  onPayment:\n    post:\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        forbid=frozenset({"OAS004"}),
    ),
    # -- OAS005/006/007: responses --------------------------------------------
    Case(
        name="response-no-description",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      responses:\n'
            '        "200": {}\n        "404": {description: nf}\n',
        ),
        expect={"OAS005": 1},
        forbid=frozenset({"OAS006"}),
    ),
    Case(
        name="operation-no-responses",
        files=_spec("", 'paths:\n  /a:\n    get:\n      operationId: a\n'),
        expect={"OAS005": 1},
    ),
    Case(
        name="default-only-response",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n'
            '      responses: {default: {description: d}}\n',
        ),
        expect={"OAS006": 1},
        forbid=frozenset({"OAS005"}),
    ),
    Case(
        name="mixed-status-responses",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      responses:\n'
            '        "200": {description: ok}\n        default: {description: d}\n',
        ),
        forbid=frozenset({"OAS006"}),
    ),
    Case(
        name="inconsistent-error-schema",
        files=_spec(
            "",
            'paths:\n'
            '  /a:\n    get:\n      operationId: a\n      responses:\n'
            '        "404": {description: e, content: {application/json:\n'
            '          {schema: {$ref: "#/components/schemas/Error"}}}}\n'
            '  /b:\n    get:\n      operationId: b\n      responses:\n'
            '        "404": {description: e, content: {application/json:\n'
            '          {schema: {$ref: "#/components/schemas/Error"}}}}\n'
            '  /c:\n    get:\n      operationId: c\n      responses:\n'
            '        "500": {description: e, content: {application/json:\n'
            '          {schema: {$ref: "#/components/schemas/Error"}}}}\n'
            '  /d:\n    get:\n      operationId: d\n      responses:\n'
            '        "404": {description: e, content: {application/json:\n'
            '          {schema: {type: string}}}}\n'
            'components:\n  schemas:\n'
            '    Error: {type: object, properties: {code: {type: string}}}\n',
        ),
        expect={"OAS007": 1},
    ),
    Case(
        name="consistent-error-schemas",
        files=_spec(
            "",
            'paths:\n'
            '  /a:\n    get:\n      operationId: a\n      responses:\n'
            '        "404": {description: e, content: {application/json:\n'
            '          {schema: {type: object}}}}\n'
            '  /b:\n    get:\n      operationId: b\n      responses:\n'
            '        "500": {description: e, content: {application/json:\n'
            '          {schema: {type: object}}}}\n'
            '  /c:\n    get:\n      operationId: c\n      responses:\n'
            '        "404": {description: e, content: {application/json:\n'
            '          {schema: {type: object}}}}\n',
        ),
        forbid=frozenset({"OAS007"}),
    ),
    # -- OAS008/009: bodies ----------------------------------------------------
    Case(
        name="request-body-no-schema",
        files=_spec(
            "",
            'paths:\n  /a:\n    post:\n      operationId: a\n'
            '      requestBody:\n        content:\n          application/json: {}\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        expect={"OAS008": 1},
    ),
    Case(
        name="request-body-with-schema",
        files=_spec(
            "",
            'paths:\n  /a:\n    post:\n      operationId: a\n'
            '      requestBody:\n        content:\n'
            '          application/json: {schema: {type: object}}\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        forbid=frozenset({"OAS008"}),
    ),
    Case(
        name="unresolved-requestbody-ref",
        files=_spec(
            "",
            'paths:\n  /a:\n    post:\n      operationId: a\n'
            "      requestBody:\n        $ref: '#/components/requestBodies/Gone'\n"
            '      responses: {"200": {description: ok}}\n',
        ),
        expect={"OAS002": 1},
        forbid=frozenset({"OAS008"}),
    ),
    Case(
        name="response-content-no-schema",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      responses:\n'
            '        "200": {description: ok, content: {application/json: {}}}\n',
        ),
        expect={"OAS009": 1},
    ),
    Case(
        name="empty-204-no-content",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      responses:\n'
            '        "204": {description: gone}\n',
        ),
        forbid=frozenset({"OAS009"}),
    ),
    # -- OAS010/011: security ---------------------------------------------------
    Case(
        name="no-security-candidate",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        expect={"OAS010": 1},
    ),
    Case(
        name="doc-security-satisfied",
        files=_spec(
            "",
            'security:\n  - bearerAuth: []\n'
            'paths:\n  /a:\n    get:\n      operationId: a\n'
            '      responses: {"200": {description: ok}}\n'
            'components:\n  securitySchemes:\n'
            '    bearerAuth: {type: http, scheme: bearer}\n',
        ),
        forbid=frozenset({"OAS010", "OAS011"}),
    ),
    Case(
        name="anonymous-doc-requirement",
        files=_spec(
            "",
            'security:\n  - {}\n'
            'paths:\n  /a:\n    get:\n      operationId: a\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        expect={"OAS010": 1},
    ),
    Case(
        name="op-security-opt-out",
        files=_spec(
            "",
            'security:\n  - bearerAuth: []\n'
            'paths:\n  /a:\n    get:\n      operationId: a\n      security: []\n'
            '      responses: {"200": {description: ok}}\n'
            'components:\n  securitySchemes:\n'
            '    bearerAuth: {type: http, scheme: bearer}\n',
        ),
        expect={"OAS011": 1},
        forbid=frozenset({"OAS010"}),
    ),
    Case(
        name="undeclared-scheme",
        files=_spec(
            "",
            'security:\n  - ghostAuth: []\n'
            'paths:\n  /a:\n    get:\n      operationId: a\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        expect={"OAS011": 1},
        forbid=frozenset({"OAS010"}),
    ),
    Case(
        name="op-adds-security-no-default",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n'
            '      security:\n        - bearerAuth: []\n'
            '      responses: {"200": {description: ok}}\n'
            'components:\n  securitySchemes:\n'
            '    bearerAuth: {type: http, scheme: bearer}\n',
        ),
        forbid=frozenset({"OAS011"}),
    ),
    # -- OAS012/013: path parameters --------------------------------------------
    Case(
        name="undeclared-template-var",
        files=_spec(
            "",
            'paths:\n  /pets/{petId}:\n    get:\n      operationId: a\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        expect={"OAS013": 1},
        forbid=frozenset({"OAS012"}),
    ),
    Case(
        name="param-not-in-template",
        files=_spec(
            "",
            'paths:\n  /pets/{petId}:\n    get:\n      operationId: a\n      parameters:\n'
            '        - {name: petId, in: path, required: true}\n'
            '        - {name: ghost, in: path, required: true}\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        expect={"OAS012": 1},
        forbid=frozenset({"OAS013"}),
    ),
    Case(
        name="param-wrong-location-no-double-report",
        files=_spec(
            "",
            'paths:\n  /pets/{petId}:\n    get:\n      operationId: a\n      parameters:\n'
            '        - {name: petId, in: query, required: true}\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        expect={"OAS012": 1},
        forbid=frozenset({"OAS013"}),
    ),
    Case(
        name="path-param-not-required",
        files=_spec(
            "",
            'paths:\n  /pets/{petId}:\n    get:\n      operationId: a\n      parameters:\n'
            '        - {name: petId, in: path}\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        expect={"OAS012": 1},
        forbid=frozenset({"OAS013"}),
    ),
    Case(
        name="path-param-declared-at-item-level",
        files=_spec(
            "",
            'paths:\n  /pets/{petId}:\n    parameters:\n'
            '      - {name: petId, in: path, required: true}\n'
            '    get:\n      operationId: a\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        forbid=frozenset({"OAS012", "OAS013"}),
    ),
    # -- OAS014: schema without type info ---------------------------------------
    Case(
        name="schema-no-type",
        files=_spec(
            "",
            'paths: {}\ncomponents:\n  schemas:\n'
            '    Empty: {description: nothing, title: e}\n'
            '    Typed: {type: object}\n'
            '    Composed: {allOf: [{$ref: "#/components/schemas/Typed"}]}\n',
        ),
        expect={"OAS014": 1},
    ),
    Case(
        name="boolean-schema-exempt",
        files=_spec(
            "",
            'paths: {}\ncomponents:\n  schemas:\n    Anything: true\n',
        ),
        forbid=frozenset({"OAS014"}),
    ),
    # -- OAS015: deprecation ----------------------------------------------------
    Case(
        name="deprecated-no-sunset",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      deprecated: true\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        expect={"OAS015": 1},
    ),
    Case(
        name="deprecated-with-x-sunset",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      deprecated: true\n'
            '      x-sunset: "2026-01-01"\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        forbid=frozenset({"OAS015"}),
    ),
    Case(
        name="deprecated-with-sunset-header",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      deprecated: true\n'
            '      responses:\n        "200":\n          description: ok\n'
            '          headers:\n            Sunset: {schema: {type: string}}\n',
        ),
        forbid=frozenset({"OAS015"}),
    ),
    # -- OAS016: server environments ---------------------------------------------
    Case(
        name="mixed-environments",
        files=_spec(
            "",
            'servers:\n  - {url: "https://api.example.com"}\n'
            '  - {url: "http://localhost:8080"}\npaths: {}\n',
        ),
        expect={"OAS016": 1},
    ),
    Case(
        name="single-environment",
        files=_spec("", 'servers:\n  - {url: "https://api.example.com"}\npaths: {}\n'),
        forbid=frozenset({"OAS016"}),
    ),
    Case(
        name="parameterized-server-skipped",
        files=_spec(
            "",
            'servers:\n  - {url: "https://{env}.example.com"}\n'
            '  - {url: "http://localhost:8080"}\npaths: {}\n',
        ),
        forbid=frozenset({"OAS016"}),
    ),
    # -- OAS017: additionalProperties ---------------------------------------------
    Case(
        name="open-additionalproperties",
        files=_spec(
            "",
            'paths: {}\ncomponents:\n  schemas:\n'
            '    Wild: {type: object, additionalProperties: true}\n'
            '    Bounded: {type: object, additionalProperties: {type: string}}\n'
            '    Closed: {type: object, additionalProperties: false}\n',
        ),
        expect={"OAS017": 1},
    ),
    Case(
        name="example-data-not-scanned",
        files=_spec(
            "",
            'paths: {}\ncomponents:\n  schemas:\n'
            '    S:\n      type: object\n'
            '      example: {additionalProperties: true}\n',
        ),
        forbid=frozenset({"OAS017"}),
    ),
    # -- OAS018: unused schemas -----------------------------------------------------
    Case(
        name="unused-schema",
        files=_spec(
            "",
            'paths: {}\ncomponents:\n  schemas:\n    Orphan: {type: object}\n',
        ),
        expect={"OAS018": 1},
    ),
    Case(
        name="referenced-schema",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      responses:\n'
            '        "200":\n          description: ok\n          content:\n'
            '            application/json:\n'
            '              schema: {$ref: "#/components/schemas/Used"}\n'
            'components:\n  schemas:\n    Used: {type: object}\n',
        ),
        forbid=frozenset({"OAS018"}),
    ),
    Case(
        name="schema-referenced-by-schema",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      responses:\n'
            '        "200":\n          description: ok\n          content:\n'
            '            application/json:\n'
            '              schema: {$ref: "#/components/schemas/Root"}\n'
            'components:\n  schemas:\n'
            '    Root: {type: object, properties: {child: {$ref: "#/components/schemas/Child"}}}\n'
            '    Child: {type: string}\n',
        ),
        forbid=frozenset({"OAS018"}),
    ),
    # -- OAS019: cycles ---------------------------------------------------------------
    Case(
        name="alias-cycle",
        files=_spec(
            "",
            'paths: {}\ncomponents:\n  schemas:\n'
            '    A: {$ref: "#/components/schemas/B"}\n'
            '    B: {$ref: "#/components/schemas/A"}\n',
        ),
        expect={"OAS019": 1},
    ),
    Case(
        name="recursive-schema",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      responses:\n'
            '        "200":\n          description: ok\n          content:\n'
            '            application/json:\n'
            '              schema: {$ref: "#/components/schemas/Node"}\n'
            'components:\n  schemas:\n'
            '    Node: {type: object, properties: {next: {$ref: "#/components/schemas/Node"}}}\n',
        ),
        expect={"OAS019": 1},
        forbid=frozenset({"OAS018"}),  # Node is referenced, not unused
    ),
    # -- OAS020: ownership --------------------------------------------------------------
    Case(
        name="untagged-operation",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        expect={"OAS020": 1},
    ),
    Case(
        name="tagged-operation",
        files=_spec(
            "",
            'paths:\n  /a:\n    get:\n      operationId: a\n      tags: [billing]\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        forbid=frozenset({"OAS020"}),
    ),
    Case(
        name="untagged-webhook-exempt",
        files=_spec(
            "",
            'paths: {}\nwebhooks:\n  onPay:\n    post:\n'
            '      responses: {"200": {description: ok}}\n',
        ),
        forbid=frozenset({"OAS020", "OAS004"}),
    ),
)


@pytest.mark.parametrize("case", PRECISION, ids=[c.name for c in PRECISION])
def test_precision(tmp_path: Path, case: Case) -> None:
    findings = _run(tmp_path, case)
    ids = [f.id for f in findings]
    for check_id, minimum in case.expect.items():
        assert ids.count(check_id) >= minimum, (
            f"{case.name}: expected >= {minimum}x {check_id}, got {sorted(set(ids))}"
        )
    for check_id in sorted(case.forbid):
        assert check_id not in ids, f"{case.name}: forbidden {check_id} fired: {findings}"


def test_catalog_covers_twenty_stable_ids() -> None:
    ids = [spec.id for spec in CATALOG]
    assert ids == [f"OAS{i:03d}" for i in range(1, 21)]
    assert all(spec.trigger for spec in CATALOG)


def test_every_finding_carries_contract_fields(tmp_path: Path) -> None:
    case = Case(
        name="contract-fields",
        files=_spec(
            "",
            'paths:\n  /a/{id}:\n    get:\n      parameters:\n'
            '        - {name: g, in: path}\n      responses: {default: {}}\n',
        ),
    )
    findings = _run(tmp_path, case)
    assert findings, "expected findings"
    for finding in findings:
        assert finding.id.startswith("OAS")
        assert finding.title and finding.description
        assert finding.severity in Severity
        assert finding.confidence in Confidence
        assert finding.evidence_kind is EvidenceKind.STATIC
        assert finding.evidence and finding.evidence[0].kind is EvidenceKind.STATIC
        assert finding.source_location is not None
        assert finding.entity_ids
        if finding.confidence is Confidence.LOW:
            assert finding.unknowns, f"{finding.id} low-confidence without unknowns"


def test_candidates_carry_unknowns(tmp_path: Path) -> None:
    case = PRECISION[[c.name for c in PRECISION].index("no-security-candidate")]
    findings = _run(tmp_path, case)
    oas010 = [f for f in findings if f.id == "OAS010"]
    assert len(oas010) == 1
    assert oas010[0].confidence is Confidence.LOW
    assert oas010[0].unknowns


def test_export_round_trip(tmp_path: Path) -> None:
    findings = _run(tmp_path, PRECISION[0])
    exported = export_findings(findings)
    payload = exported.to_json()
    assert payload == export_findings(findings).to_json()
    assert "OAS001" in payload


def test_determinism_over_repeated_runs(tmp_path: Path) -> None:
    files = _spec(
        "",
        'servers:\n  - {url: "https://api.example.com"}\n  - {url: "http://localhost"}\n'
        'paths:\n  /pets/{petId}:\n    get:\n      deprecated: true\n'
        '      parameters:\n        - {name: ghost, in: path, required: true}\n'
        '      responses: {default: {}}\n'
        'components:\n  schemas:\n    Wild: {type: object, additionalProperties: true}\n',
    )
    _write(tmp_path, files)
    model = load_openapi_project(ProjectContext.from_root(tmp_path))
    first = export_findings(run_openapi_checks(model)).to_json()
    second = export_findings(run_openapi_checks(model)).to_json()
    assert first == second


def test_determinism_over_input_order(tmp_path: Path) -> None:
    files = {
        "a.yaml": HEADER + 'paths:\n  /a:\n    get:\n      responses: {default: {}}\n',
        "b.yaml": HEADER + 'paths:\n  /b:\n    get: {operationId: x}\n',
    }
    _write(tmp_path, files)
    ctx = ProjectContext.from_root(tmp_path)
    forward = export_findings(
        run_openapi_checks(load_openapi_project(ctx, ["a.yaml", "b.yaml"]))
    ).to_json()
    reverse = export_findings(
        run_openapi_checks(load_openapi_project(ctx, ["b.yaml", "a.yaml"]))
    ).to_json()
    assert forward == reverse
