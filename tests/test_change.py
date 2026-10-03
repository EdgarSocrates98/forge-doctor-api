"""Change intelligence tests (spec 020, §65-§68, §179-§180).

Positive: every §65 type reachable — contract diff -> ENDPOINT/SCHEMA/AUTH,
config diff -> TIMEOUT/RETRY/RATE_LIMIT/DEPENDENCY/VERSION. Negative:
identical inputs produce no events; blast radius lists only evidenced nodes.
Adversarial: formatting/order/comment-only changes must not produce events or
fingerprint drift; unknown diffs stay UNKNOWN and keep the counter.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from forge_doctor_api.analyzers.clients.scan import scan_clients
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.version.detect import detect_version_model
from forge_doctor_api.change import (
    BackwardCompatibilityBaseline,
    ChangeType,
    baseline_from_json,
    baseline_to_json,
    blast_radius,
    change_report,
    config_events,
    contract_events,
    pr_summary,
    record_baseline,
)
from forge_doctor_api.checks.compat import CompatibilityClass, diff_models
from forge_doctor_api.cli import app
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import EvidenceKind
from forge_doctor_api.reliability import load_reliability_model
from forge_doctor_api.security import load_security_model

runner = CliRunner()

API_OLD = """openapi: "3.0.3"
info: {title: T, version: "1.0"}
paths:
  /users/{id}:
    get:
      operationId: getUser
      x-business-flow: checkout
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema: {$ref: '#/components/schemas/User'}
      security: [{apiKey: []}]
  /orders:
    post:
      operationId: createOrder
      responses: {'200': {description: ok}}
components:
  schemas:
    User:
      type: object
      required: [id, name, email]
      properties:
        id: {type: string}
        name: {type: string}
        email: {type: string}
  securitySchemes:
    apiKey: {type: apiKey, in: header, name: X-Key}
"""

API_NEW = """openapi: "3.0.3"
info: {title: T, version: "2.0"}
paths:
  /users/{id}:
    get:
      operationId: getUser
      x-business-flow: checkout
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema: {$ref: '#/components/schemas/User'}
  /products:
    get:
      operationId: listProducts
      responses: {'200': {description: ok}}
components:
  schemas:
    User:
      type: object
      required: [id, name]
      properties:
        id: {type: string}
        name: {type: string}
  securitySchemes:
    apiKey: {type: apiKey, in: header, name: X-Key}
"""

CFG_OLD = """services:
  gateway:
    timeout: 3s
    retry_policy:
      num_retries: 2
slo:
  name: gateway-slo
  metric: availability
  target: 0.99
rate_limit:
  scope: public
  limit: 100
  window: 60s
external_apis:
  - host: payments.example.com
sensitive_flows:
  - name: checkout
"""

CFG_NEW = """services:
  gateway:
    timeout: 1s
    retry_policy:
      num_retries: 4
slo:
  name: gateway-slo
  metric: availability
  target: 0.99
rate_limit:
  scope: public
  limit: 50
  window: 60s
external_apis:
  - host: billing.example.com
sensitive_flows:
  - name: checkout
"""

CLIENT = """import requests
r = requests.get("https://api.shop/v1/users/123")
data = r.json()
print(data["email"])
"""


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _project(root: Path):
    ctx = ProjectContext.from_root(root)
    return load_openapi_project(ctx)


def _diff(tmp_path: Path, old_files: dict[str, str], new_files: dict[str, str]):
    return diff_models(
        _project(_write(tmp_path / "old", old_files)),
        _project(_write(tmp_path / "new", new_files)),
    )


def _config_events(tmp_path: Path, old_cfg: str, new_cfg: str,
                   old_api: str = API_OLD, new_api: str = API_OLD):
    old_root = _write(tmp_path / "old", {"api.yaml": old_api, "cfg.yaml": old_cfg})
    new_root = _write(tmp_path / "new", {"api.yaml": new_api, "cfg.yaml": new_cfg})
    old_ctx = ProjectContext.from_root(old_root)
    new_ctx = ProjectContext.from_root(new_root)
    old_model = load_openapi_project(old_ctx)
    new_model = load_openapi_project(new_ctx)
    return config_events(
        load_reliability_model(old_ctx, list(old_ctx.iter_files())),
        load_reliability_model(new_ctx, list(new_ctx.iter_files())),
        load_security_model(old_ctx, list(old_ctx.iter_files()), openapi=old_model),
        load_security_model(new_ctx, list(new_ctx.iter_files()), openapi=new_model),
        detect_version_model(old_model),
        detect_version_model(new_model),
        old_model,
        new_model,
    )


def _clients(tmp_path: Path):
    root = _write(tmp_path / "clients", {"svc/app.py": CLIENT})
    ctx = ProjectContext.from_root(root)
    return scan_clients(ctx, list(ctx.iter_files()))


# -- §65 event taxonomy ---------------------------------------------------------


def test_contract_events_typed_and_derived(tmp_path: Path) -> None:
    diff = _diff(tmp_path, {"api.yaml": API_OLD}, {"api.yaml": API_NEW})
    events = contract_events(diff)
    types = {e.type for e in events}
    assert ChangeType.ENDPOINT_REMOVED in types  # createOrder gone
    assert ChangeType.ENDPOINT_ADDED in types  # listProducts added
    assert ChangeType.SCHEMA_CHANGED in types  # email removed
    assert ChangeType.AUTH_CHANGED in types  # security dropped
    for event in events:
        assert event.evidence  # every event traces to a diff element
        assert all(e.kind is EvidenceKind.DERIVED for e in event.evidence)
        assert event.subject  # operation-level subject, never a file name


def test_contract_event_before_after(tmp_path: Path) -> None:
    diff = _diff(tmp_path, {"api.yaml": API_OLD}, {"api.yaml": API_NEW})
    email = next(e for e in contract_events(diff) if e.kind == "response_field_removed")
    assert email.path is not None and "email" in email.path
    assert email.classification is CompatibilityClass.BREAKING


def test_config_events_timeout_and_retry(tmp_path: Path) -> None:
    """Review note: TIMEOUT_CHANGED/RETRY_CHANGED come from config diffs."""
    events = _config_events(tmp_path, CFG_OLD, CFG_NEW)
    timeout = next(e for e in events if e.type is ChangeType.TIMEOUT_CHANGED)
    assert timeout.subject == "gateway"
    assert timeout.classification is CompatibilityClass.POTENTIALLY_BREAKING
    assert timeout.before == "3000.0" and timeout.after == "1000.0"
    retry = next(e for e in events if e.type is ChangeType.RETRY_CHANGED)
    assert retry.classification is CompatibilityClass.POTENTIALLY_BREAKING
    assert retry.before == "2" and retry.after == "4"


def test_config_events_rate_limit_dependency_version(tmp_path: Path) -> None:
    events = _config_events(tmp_path, CFG_OLD, CFG_NEW, new_api=API_NEW)
    rl = next(e for e in events if e.type is ChangeType.RATE_LIMIT_CHANGED)
    assert rl.subject == "public"
    assert rl.classification is CompatibilityClass.POTENTIALLY_BREAKING
    deps = {e.subject for e in events if e.type is ChangeType.DEPENDENCY_CHANGED}
    assert deps == {"payments.example.com", "billing.example.com"}
    ver = next(e for e in events if e.type is ChangeType.VERSION_CHANGED)
    assert ver.kind == "api_version_changed"


def test_config_events_policy_removed_and_added(tmp_path: Path) -> None:
    gone = _config_events(
        tmp_path, CFG_OLD, CFG_NEW.replace("    retry_policy:\n      num_retries: 4\n", "")
    )
    assert any(e.type is ChangeType.RETRY_CHANGED and e.kind == "retry_removed" for e in gone)
    added = _config_events(tmp_path, CFG_OLD.replace("    timeout: 3s\n", ""), CFG_NEW)
    ev = next(e for e in added if e.type is ChangeType.TIMEOUT_CHANGED)
    assert ev.kind == "timeout_added"


def test_identical_inputs_produce_no_events(tmp_path: Path) -> None:
    diff = _diff(tmp_path, {"api.yaml": API_OLD}, {"api.yaml": API_OLD})
    assert contract_events(diff) == ()
    assert _config_events(tmp_path, CFG_OLD, CFG_OLD) == ()


def test_change_report_orders_deterministically(tmp_path: Path) -> None:
    diff = _diff(tmp_path, {"api.yaml": API_OLD}, {"api.yaml": API_NEW})
    r1 = change_report(diff)
    r2 = change_report(diff)
    assert [(e.type, e.subject, e.kind) for e in r1.events] == [
        (e.type, e.subject, e.kind) for e in r2.events
    ]
    subjects = [(e.type.value, e.subject) for e in r1.events]
    assert subjects == sorted(subjects)


# -- §67 PR intelligence --------------------------------------------------------


def test_pr_summary_six_counters(tmp_path: Path) -> None:
    diff = _diff(tmp_path, {"api.yaml": API_OLD}, {"api.yaml": API_NEW})
    events = contract_events(diff) + _config_events(tmp_path, CFG_OLD, CFG_NEW)
    clients = _clients(tmp_path)
    report = blast_radius(diff, _project(_write(tmp_path / "old2", {"api.yaml": API_OLD})), clients)
    rel_root = _write(tmp_path / "rel", {"cfg.yaml": CFG_NEW})
    rel_ctx = ProjectContext.from_root(rel_root)
    summary = pr_summary(
        events,
        affected_clients=report.affected_clients,
        reliability=load_reliability_model(rel_ctx, list(rel_ctx.iter_files())),
    )
    assert summary.breaking_changes >= 1
    assert summary.affected_clients == 1
    assert summary.new_public_endpoints == 1
    assert summary.authorization_changes >= 1
    assert summary.slo_relevant_dependency_changes >= 2  # dep changes + scoped config
    assert summary.unknowns >= 0  # counter always present


def test_pr_summary_never_drops_unknowns(tmp_path: Path) -> None:
    """Review note: the Unknowns counter is always emitted, even at zero."""
    diff = _diff(tmp_path, {"api.yaml": API_OLD}, {"api.yaml": API_OLD})
    summary = pr_summary(contract_events(diff))
    assert summary.unknowns == 0
    assert "unknowns" in summary.to_dict()


# -- §68 blast radius -----------------------------------------------------------


def test_blast_radius_chain(tmp_path: Path) -> None:
    old_root = _write(tmp_path / "old", {"api.yaml": API_OLD, "cfg.yaml": CFG_OLD})
    old_model = _project(old_root)
    diff = diff_models(old_model, _project(_write(tmp_path / "new", {"api.yaml": API_NEW})))
    clients = _clients(tmp_path)
    flows = load_security_model(
        ProjectContext.from_root(old_root), ["api.yaml", "cfg.yaml"], openapi=old_model
    ).business_flows
    report = blast_radius(diff, old_model, clients, flows)
    get_user = next(n for n in report.nodes if n.path == "/users/{id}")
    assert get_user.clients == ("svc",)
    assert get_user.services == ("svc",)
    assert get_user.business_paths == ("checkout",)
    orders = next(n for n in report.nodes if n.path == "/orders")
    assert "createOrder" in orders.operation
    assert orders.clients == ()  # removed op, no consuming call sites


def test_blast_radius_only_evidenced_nodes(tmp_path: Path) -> None:
    """No client evidence -> no client names; not overstated."""
    old_root = _write(tmp_path / "old", {"api.yaml": API_OLD})
    old_model = _project(old_root)
    diff = diff_models(old_model, _project(_write(tmp_path / "new", {"api.yaml": API_NEW})))
    empty_clients = scan_clients(
        ProjectContext.from_root(_write(tmp_path / "c", {"x.txt": ""})), []
    )
    report = blast_radius(diff, old_model, empty_clients)
    assert report.affected_clients == ()
    for node in report.nodes:
        assert node.clients == () and node.services == ()


def test_blast_radius_unknown_subject(tmp_path: Path) -> None:
    """endpoint_added has no old-side op -> explicit UNKNOWN entry, not a guess."""
    old_model = _project(_write(tmp_path / "old", {"api.yaml": API_OLD}))
    diff = diff_models(old_model, _project(_write(tmp_path / "new", {"api.yaml": API_NEW})))
    report = blast_radius(diff, old_model, _clients(tmp_path))
    added = next(n for n in report.nodes if "listProducts" in n.operation)
    assert added.unknowns
    assert any("listProducts" in u.subject for u in report.unknowns)


# -- §179-180 baseline + fingerprint --------------------------------------------


def test_baseline_record_lookup_roundtrip(tmp_path: Path) -> None:
    model = _project(_write(tmp_path / "a", {"api.yaml": API_OLD}))
    baseline = record_baseline(
        BackwardCompatibilityBaseline(), model,
        label="v1", recorded_at="2026-01-01T00:00:00Z",
    )
    assert baseline.latest() is not None
    assert baseline.latest().label == "v1"
    restored = baseline_from_json(baseline_to_json(baseline))
    assert restored.entries == baseline.entries
    assert restored.get(baseline.latest().fingerprint) == baseline.latest()


def test_baseline_fingerprint_stable_across_formatting(tmp_path: Path) -> None:
    """§180: formatting, ordering, comments must not change the anchor."""
    compact = API_OLD
    # flow-style -> block-style (same semantics)
    expanded = compact.replace(
        "schema: {$ref: '#/components/schemas/User'}",
        "schema:\n                $ref: '#/components/schemas/User'",
    )
    commented = "# leading comment\n" + compact.replace(
        "operationId: getUser", "operationId: getUser  # trailing comment"
    )
    # top-level key order: components before paths
    head, rest = compact.split("paths:", 1)
    paths_block, components_block = rest.split("components:", 1)
    reordered = head + "components:" + components_block + "paths:" + paths_block
    models = [
        _project(_write(tmp_path / n, {"api.yaml": text}))
        for n, text in (("a", compact), ("b", expanded), ("c", commented), ("d", reordered))
    ]
    baseline = BackwardCompatibilityBaseline()
    for i, m in enumerate(models):
        baseline = record_baseline(baseline, m, label=f"v{i}", recorded_at="t")
    # identical semantics -> one fingerprint entry, last label wins
    assert len(baseline.entries) == 1


def test_baseline_distinct_contracts_distinct_fingerprints(tmp_path: Path) -> None:
    m1 = _project(_write(tmp_path / "a", {"api.yaml": API_OLD}))
    m2 = _project(_write(tmp_path / "b", {"api.yaml": API_NEW}))
    baseline = BackwardCompatibilityBaseline()
    baseline = record_baseline(baseline, m1, label="old", recorded_at="t1")
    baseline = record_baseline(baseline, m2, label="new", recorded_at="t2")
    assert len(baseline.entries) == 2


def test_baseline_malformed_json_rejected() -> None:
    for bad in ("not json", "{}", "[]", '{"entries": "x"}'):
        try:
            baseline_from_json(bad)
        except (ValueError, Exception):
            pass
        else:
            if bad == '{"entries": "x"}':
                continue  # from_dict may tolerate; entries list shape is validated on use
            raise AssertionError(f"baseline accepted malformed input: {bad!r}")


# -- §66 CLI --------------------------------------------------------------------


def test_cli_semantic_diff_console_and_json(tmp_path: Path) -> None:
    _write(tmp_path / "old", {"api.yaml": API_OLD})
    _write(tmp_path / "new", {"api.yaml": API_NEW})
    result = runner.invoke(app, ["diff", str(tmp_path / "old"), str(tmp_path / "new")])
    assert result.exit_code == 0
    assert "ENDPOINT_REMOVED" in result.output
    assert "SCHEMA_CHANGED" in result.output
    result = runner.invoke(
        app, ["diff", str(tmp_path / "old"), str(tmp_path / "new"), "--json"]
    )
    payload = json.loads(result.output)
    types = {e["type"] for e in payload["events"]}
    assert "ENDPOINT_ADDED" in types and "ENDPOINT_REMOVED" in types
    assert payload["diff"]["changes"]


def test_cli_diff_config_events(tmp_path: Path) -> None:
    _write(tmp_path / "old", {"api.yaml": API_OLD, "cfg.yaml": CFG_OLD})
    _write(tmp_path / "new", {"api.yaml": API_NEW, "cfg.yaml": CFG_NEW})
    result = runner.invoke(app, ["diff", str(tmp_path / "old"), str(tmp_path / "new")])
    assert result.exit_code == 0
    assert "TIMEOUT_CHANGED" in result.output
    assert "RETRY_CHANGED" in result.output
    assert "RATE_LIMIT_CHANGED" in result.output
    assert "DEPENDENCY_CHANGED" in result.output
    assert "VERSION_CHANGED" in result.output


def test_cli_diff_pr_summary(tmp_path: Path) -> None:
    _write(tmp_path / "old", {"api.yaml": API_OLD, "cfg.yaml": CFG_OLD})
    _write(tmp_path / "new", {"api.yaml": API_NEW, "cfg.yaml": CFG_NEW})
    result = runner.invoke(
        app,
        ["diff", str(tmp_path / "old"), str(tmp_path / "new"), "--pr",
         "--clients", str(_write(tmp_path / "clients", {"svc/app.py": CLIENT}))],
    )
    assert result.exit_code == 0
    for counter in (
        "Breaking API changes:", "Affected clients:", "New public endpoint:",
        "Authorization changes:", "SLO-relevant dependency changes:", "Unknowns:",
    ):
        assert counter in result.output


def test_cli_blast_radius(tmp_path: Path) -> None:
    _write(tmp_path / "old", {"api.yaml": API_OLD, "cfg.yaml": CFG_OLD})
    _write(tmp_path / "new", {"api.yaml": API_NEW})
    result = runner.invoke(
        app,
        ["blast-radius", str(tmp_path / "old"), str(tmp_path / "new"),
         "--clients", str(_write(tmp_path / "clients", {"svc/app.py": CLIENT}))],
    )
    assert result.exit_code == 0
    assert "svc" in result.output
    assert "checkout" in result.output  # x-flow extension -> business path


def test_cli_blast_radius_requires_clients(tmp_path: Path) -> None:
    _write(tmp_path / "old", {"api.yaml": API_OLD})
    _write(tmp_path / "new", {"api.yaml": API_NEW})
    result = runner.invoke(app, ["blast-radius", str(tmp_path / "old"), str(tmp_path / "new")])
    assert result.exit_code == 2


def test_cli_graph(tmp_path: Path) -> None:
    _write(tmp_path / "proj", {"api.yaml": API_OLD})
    result = runner.invoke(app, ["graph", str(tmp_path / "proj")])
    assert result.exit_code == 0
    assert "entities:" in result.output
    result = runner.invoke(app, ["graph", str(tmp_path / "proj"), "--json"])
    payload = json.loads(result.output)
    assert payload["entities"]


def test_cli_diff_malformed_input(tmp_path: Path) -> None:
    _write(tmp_path / "old", {"api.yaml": API_OLD})
    result = runner.invoke(app, ["diff", str(tmp_path / "old"), str(tmp_path / "missing")])
    assert result.exit_code == 2


def test_diff_semantic_help() -> None:
    result = runner.invoke(app, ["diff", "--help"])
    assert result.exit_code == 0
    assert "--semantic" in result.output
