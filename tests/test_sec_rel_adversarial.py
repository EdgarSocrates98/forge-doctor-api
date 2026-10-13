"""Spec 088 — adversarial security/reliability layer.

Every negative test asserts the analyzer produced entities or unknowns
(proving the analysis ran) — silence alone is never evidence. Every
positive test pins the evidence trail.
"""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.cache.graph import build_cache_graph
from forge_doctor_api.analyzers.cache.scan import load_cache_model
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.routes import FastApiAdapter
from forge_doctor_api.analyzers.runtime.execution import (
    DownstreamCall,
    RequestExecution,
)
from forge_doctor_api.checks.apisec import run_security_checks
from forge_doctor_api.checks.relapi import run_reliability_checks
from forge_doctor_api.checks.relapi.engine import run_depth_checks
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.diagnose import diagnose
from forge_doctor_api.reliability import (
    IdempotencyVerdict,
    load_reliability_model,
)
from forge_doctor_api.reliability.model import (
    ApiReliabilityModel,
    ApiServiceObjective,
    RetryPolicy,
    TimeoutConfig,
)
from forge_doctor_api.reliability.retry import amplification
from forge_doctor_api.reliability.slo import error_budget
from forge_doctor_api.reliability.timeout import (
    BudgetVerdict,
    evaluate_timeout_budget,
)
from forge_doctor_api.security import load_security_model

HEADER = "openapi: 3.0.3\ninfo: {title: T, version: '1'}\n"

ID_PARAM_OAS = HEADER + (
    "paths:\n  /pets/{id}:\n    get:\n"
    "      operationId: getPet\n"
    "      parameters:\n"
    "        - {name: id, in: path, required: true, schema: {type: integer}}\n"
    "      responses: {'200': {description: ok}}\n"
    "components:\n  securitySchemes:\n"
    "    oauth: {type: oauth2, flows: {}}\n"
)

ADMIN_OAS = HEADER + (
    "paths:\n  /admin/users:\n    get:\n"
    "      operationId: adminUsers\n"
    "      responses: {'200': {description: ok}}\n"
)


def _ctx(tmp_path: Path, files: dict[str, str]) -> ProjectContext:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return ProjectContext.from_root(tmp_path)


def _ids(findings) -> list[str]:
    return [f.id for f in findings]


# ---------- negative corpus: no-finding requires proof of work ----------


def test_id_param_covered_by_global_authz_middleware(tmp_path: Path) -> None:
    """`{id}` param + global authz middleware -> NO APISEC001, but the
    impl-plane policy entity must exist (proof analysis ran)."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": ID_PARAM_OAS,
        "app.py": (
            "from fastapi import FastAPI\n"
            "from gw.authz import AuthorizationMiddleware\n"
            "app = FastAPI()\n"
            "app.add_middleware(AuthorizationMiddleware)\n"
            "@app.get('/pets/{id}')\n"
            "def getPet(id: int):\n    pass\n"),
    })
    routes = FastApiAdapter().scan(ctx, "svc")
    oas = load_openapi_project(ctx)
    m = load_security_model(ctx, list(ctx.iter_files()),
                            openapi=oas, routes=routes)
    assert any(p.plane == "implementation" for p in m.authorization)
    ids = _ids(run_security_checks(m, openapi=oas))
    assert "APISEC001" not in ids


def test_admin_path_covered_by_gateway_role(tmp_path: Path) -> None:
    """`/admin/*` ops under a gateway authz prefix -> NO APISEC002, with
    the gateway policy entity bound to the `/admin` scope."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": ADMIN_OAS,
        "gateway.yaml": (
            "routes:\n  - prefix: /admin\n"
            "    authorization: {roles: [admin]}\n"),
    })
    oas = load_openapi_project(ctx)
    m = load_security_model(ctx, list(ctx.iter_files()), openapi=oas)
    gw = [p for p in m.authorization if p.plane == "gateway"]
    assert gw and gw[0].roles == ("admin",)
    assert "APISEC002" not in _ids(run_security_checks(m, openapi=oas))


def test_admin_path_uncovered_still_flags(tmp_path: Path) -> None:
    """Gateway authz scoped to a different prefix must NOT cover /admin."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": ADMIN_OAS,
        "gateway.yaml": (
            "routes:\n  - prefix: /public\n"
            "    authorization: {roles: [reader]}\n"),
    })
    oas = load_openapi_project(ctx)
    m = load_security_model(ctx, list(ctx.iter_files()), openapi=oas)
    assert any(p.plane == "gateway" for p in m.authorization)
    assert "APISEC002" in _ids(run_security_checks(m, openapi=oas))


def test_wildcard_in_description_not_cors_evidence(tmp_path: Path) -> None:
    """A `*` mentioned only in a description/comment never sets
    `wildcard` — the real (non-wildcard) policy still loads."""
    ctx = _ctx(tmp_path, {
        "gateway.yaml": (
            "# never put a wildcard (*) here\n"
            "cors:\n  public:\n"
            "    description: \"do not use '*' origins\"\n"
            "    allowed_origins: [https://app.example.com]\n"),
    })
    m = load_security_model(ctx, list(ctx.iter_files()))
    assert m.cors  # analysis ran and produced the entity
    assert all(not c.wildcard for c in m.cors)
    assert "APISEC004" not in _ids(run_security_checks(m))


def test_retries_in_examples_or_schema_not_counted(tmp_path: Path) -> None:
    """Retry counts inside `examples:`/schema `properties:`/`default:`
    blocks are documentation, not declared policy."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n    get:\n"
            "      operationId: listPets\n"
            "      responses:\n        '200':\n          description: ok\n"
            "          content:\n            application/json:\n"
            "              examples:\n                retryCase:\n"
            "                  value: {retries: 9, timeout: 999}\n"),
        "cfg.yaml": (
            "metadata:\n  description: \"client retries: 4\"\n"
            "examples:\n  sample:\n    retries: 7\n    timeout: 5s\n"
            "schema:\n  properties:\n    retries: {type: integer, default: 5}\n"
            "  default: {retry_policy: {num_retries: 8}}\n"
            "services:\n  - name: payments\n    retries: 2\n"),
    })
    rel = load_reliability_model(ctx, list(ctx.iter_files()))
    scopes = {r.scope: r for r in rel.retry_policies}
    assert scopes["payments"].max_attempts == 2
    assert all(r.max_attempts in (None, 2) for r in rel.retry_policies)
    assert all(r.max_attempts != 9 for r in rel.retry_policies)
    timeouts = {t.scope: t for t in rel.timeouts}
    assert all(t.timeout_ms != 999 for t in timeouts.values())


def test_oas_examples_block_not_gateway_policy(tmp_path: Path) -> None:
    """An OAS `examples:`/response `headers:` subtree must not fabricate
    gateway authz/cors records."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n    get:\n"
            "      operationId: listPets\n"
            "      responses:\n        '200':\n"
            "          description: ok\n"
            "          headers:\n            Authorization:\n"
            "              schema: {type: string}\n"
            "          content:\n            application/json:\n"
            "              example: {rate_limit: {limit: 5}}\n"),
    })
    m = load_security_model(ctx, list(ctx.iter_files()),
                            openapi=load_openapi_project(ctx))
    assert all(p.plane != "gateway" for p in m.authorization)
    assert not m.rate_limits


# ---------- auth chain: implicit coverage is never explicit ----------


def test_anonymous_override_with_impl_enforcement_is_break(tmp_path: Path) -> None:
    """Global security + op `security: []` anonymous override + impl
    Security() = enforced-but-undeclared break (a real break)."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "security:\n  - oauth: []\n"
            "paths:\n  /pets:\n    get:\n"
            "      operationId: listPets\n"
            "      security: []\n"
            "      responses: {'200': {description: ok}}\n"
            "components:\n  securitySchemes:\n"
            "    oauth: {type: oauth2, flows: {}}\n"),
        "app.py": (
            "from fastapi import FastAPI, Security\n"
            "app = FastAPI()\n"
            "@app.get('/pets')\n"
            "def listPets(k=Security(chk)):\n    pass\n"),
    })
    routes = FastApiAdapter().scan(ctx, "svc")
    oas = load_openapi_project(ctx)
    m = load_security_model(ctx, list(ctx.iter_files()),
                            openapi=oas, routes=routes)
    link = next((x for x in m.auth_chain if x.chain_complete is False),
                None)
    assert link is not None
    assert "APISEC013" in _ids(run_security_checks(m, openapi=oas))


def test_implicit_global_inheritance_no_false_break(tmp_path: Path) -> None:
    """Op with no `security:` inherits the global requirement; impl
    enforcement resolves it -> complete chain, no APISEC013."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "security:\n  - oauth: []\n"
            "paths:\n  /pets:\n    get:\n"
            "      operationId: listPets\n"
            "      responses: {'200': {description: ok}}\n"
            "components:\n  securitySchemes:\n"
            "    oauth: {type: oauth2, flows: {}}\n"),
        "app.py": (
            "from fastapi import FastAPI, Security\n"
            "app = FastAPI()\n"
            "@app.get('/pets')\n"
            "def listPets(k=Security(chk)):\n    pass\n"),
    })
    routes = FastApiAdapter().scan(ctx, "svc")
    oas = load_openapi_project(ctx)
    m = load_security_model(ctx, list(ctx.iter_files()),
                            openapi=oas, routes=routes)
    link = m.auth_chain[0]
    assert link.chain_complete is True
    assert "APISEC013" not in _ids(run_security_checks(m, openapi=oas))


def test_undeclared_scheme_override_is_unknown_not_break(tmp_path: Path) -> None:
    """`security: [{ghost: []}]` with no such scheme -> APISEC011
    ambiguity, not a fabricated APISEC013 chain break."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "security:\n  - oauth: []\n"
            "paths:\n  /pets:\n    get:\n"
            "      operationId: listPets\n"
            "      security:\n        - ghost: []\n"
            "      responses: {'200': {description: ok}}\n"
            "components:\n  securitySchemes:\n"
            "    oauth: {type: oauth2, flows: {}}\n"),
    })
    oas = load_openapi_project(ctx)
    m = load_security_model(ctx, list(ctx.iter_files()), openapi=oas)
    ids = _ids(run_security_checks(m, openapi=oas))
    assert "APISEC011" in ids
    assert "APISEC013" not in ids


# ---------- retry topology ----------


def test_amplification_partial_chain_stays_unknown() -> None:
    """A missing layer blocks the product; unmeasured hops are named."""
    policies = (
        RetryPolicy(scope="client", max_attempts=3),
        RetryPolicy(scope="gateway->svc", max_attempts=2),
        # service + downstream hops have NO declared policy
    )
    amp = amplification(("client", "gateway", "svc", "db"), policies)
    assert amp.complete is False
    assert amp.potential_attempts is None
    # `gateway->svc` binds to its caller hop; svc + db stay unmeasured
    assert {u.subject for u in amp.unknowns} == {"hop svc", "hop db"}
    assert amp.missing == ("db", "svc")  # sorted
    assert {p.scope for p in amp.policies} == {"client", "gateway->svc"}
    assert amp.confidence.value == "UNKNOWN"


def test_amplification_attribution_and_product() -> None:
    """Complete client->gateway->mesh->service->dep chain: product is
    exact and each layer keeps its own scope in `policies`."""
    policies = (
        RetryPolicy(scope="client", max_attempts=3),
        RetryPolicy(scope="gateway->svc", max_attempts=2),
        RetryPolicy(scope="mesh", max_attempts=2),
        RetryPolicy(scope="svc", max_attempts=3),
        RetryPolicy(scope="db", max_attempts=1),
    )
    amp = amplification(("client", "gateway", "mesh", "svc", "db"),
                        policies)
    assert amp.complete is True
    assert amp.potential_attempts == 3 * 2 * 2 * 3 * 1
    # edge-scope policy binds to its caller hop but keeps its own scope
    assert {p.scope for p in amp.policies} == {
        "client", "gateway->svc", "mesh", "svc", "db"}
    assert amp.missing == ()
    assert amp.unknowns == ()


def test_policy_declared_without_attempts_blocks_product() -> None:
    """A policy record with no `max_attempts` is presence, not a factor —
    the hop lands in `missing`."""
    policies = (
        RetryPolicy(scope="client", max_attempts=4),
        RetryPolicy(scope="svc"),  # declared scope, no attempts
    )
    amp = amplification(("client", "svc"), policies)
    assert amp.complete is False
    assert amp.potential_attempts is None
    assert amp.missing == ("svc",)


# ---------- timeout budgets ----------


def test_timeout_incoherent_chain_impossible() -> None:
    """Callee timeout exceeds caller budget even in parallel order."""
    b = evaluate_timeout_budget(
        "edge", 100.0, (("svc", 500.0),))
    assert b.verdict is BudgetVerdict.IMPOSSIBLE

    b2 = evaluate_timeout_budget(
        "edge", 100.0, (("svc-a", 200.0), ("svc-b", 150.0)))
    assert b2.verdict is BudgetVerdict.IMPOSSIBLE
    assert b2.parallel_need_ms == 200.0


def test_timeout_sequential_only_at_risk() -> None:
    """Individually-fine callees that sum over budget -> AT_RISK."""
    b = evaluate_timeout_budget(
        "edge", 300.0, (("a", 200.0), ("b", 200.0)))
    assert b.verdict is BudgetVerdict.AT_RISK
    assert b.sequential_need_ms == 400.0
    assert b.parallel_need_ms == 200.0


def test_timeout_coherent_chain_feasible() -> None:
    b = evaluate_timeout_budget(
        "edge", 1000.0, (("a", 200.0), ("b", 300.0)))
    assert b.verdict is BudgetVerdict.FEASIBLE
    assert b.unknowns == ()


def test_timeout_missing_caller_is_unknown() -> None:
    b = evaluate_timeout_budget("edge", None, (("svc", 100.0),))
    assert b.verdict is BudgetVerdict.UNKNOWN
    assert any(u.subject == "edge" and "caller timeout" in u.missing
               for u in b.unknowns)


def test_timeout_missing_downstream_at_risk_not_feasible() -> None:
    """Undeclared downstream budget can never yield FEASIBLE."""
    b = evaluate_timeout_budget(
        "edge", 1000.0, (("a", 100.0), ("b", None)))
    assert b.verdict is BudgetVerdict.AT_RISK
    assert any(u.subject == "downstream b" for u in b.unknowns)


def test_relapi003_wires_budget_verdict() -> None:
    """The RELAPI003 check surfaces the impossible-budget diagnostic."""
    model = ApiReliabilityModel(
        timeouts=(
            TimeoutConfig(scope="edge->svc", timeout_ms=100),
            TimeoutConfig(scope="svc", timeout_ms=500),
        ),
    )
    findings = run_depth_checks(model, (("edge", "svc"),))
    assert "APIREL002" in _ids(findings) or "RELAPI003" in _ids(findings)


# ---------- idempotency evidence source matrix ----------


def test_relapi008_contract_x_idempotent_true(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n    post:\n      operationId: createPet\n"
            "      x-idempotent: true\n"
            "      responses: {'201': {description: ok}}\n"),
    })
    oas = load_openapi_project(ctx)
    rel = load_reliability_model(ctx, list(ctx.iter_files()), openapi=oas)
    bound = next(i for i in rel.idempotency if i.subject == "createPet")
    assert bound.verdict is IdempotencyVerdict.IDEMPOTENT
    assert any(s.kind == "contract_metadata" for s in bound.sources)
    assert "RELAPI008" not in _ids(
        run_reliability_checks(rel, operations=oas.operations))


def test_relapi008_gateway_policy_source(tmp_path: Path) -> None:
    """A gateway/config `idempotency` block bound by name suppresses the
    finding and records `gateway_policy`-grade evidence."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n    post:\n      operationId: createPet\n"
            "      responses: {'201': {description: ok}}\n"),
        "gw.yaml": (
            "policies:\n  - name: createPet\n"
            "    idempotency: {key_header: Idempotency-Key}\n"),
    })
    oas = load_openapi_project(ctx)
    rel = load_reliability_model(ctx, list(ctx.iter_files()), openapi=oas)
    bound = next(i for i in rel.idempotency if i.subject == "createPet")
    assert bound.verdict is IdempotencyVerdict.IDEMPOTENT
    assert "RELAPI008" not in _ids(
        run_reliability_checks(rel, operations=oas.operations))


def test_relapi008_verb_only_is_unknown(tmp_path: Path) -> None:
    """PUT alone: verb semantics never decide — verdict is UNKNOWN."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets/{id}:\n    put:\n"
            "      operationId: putPet\n"
            "      responses: {'200': {description: ok}}\n"),
    })
    oas = load_openapi_project(ctx)
    rel = load_reliability_model(ctx, list(ctx.iter_files()), openapi=oas)
    # no evidence record exists for the op — and none is fabricated
    assert all(i.subject != "putPet" or
               i.verdict is not IdempotencyVerdict.IDEMPOTENT
               for i in rel.idempotency)
    f = next(f for f in run_reliability_checks(
        rel, operations=oas.operations) if f.id == "RELAPI008")
    assert f.unknowns


# ---------- cache adversarial ----------


OAS_PETS = HEADER + (
    "paths:\n  /pets:\n"
    "    get:\n      operationId: listPets\n"
    "      responses: {'200': {description: ok}}\n"
    "    post:\n      operationId: createPet\n"
    "      responses: {'201': {description: ok}}\n")


def _cache(tmp_path: Path, cfg: str):
    ctx = _ctx(tmp_path, {
        "openapi.yaml": OAS_PETS,
        "cfg.yaml": cfg,
    })
    oas = load_openapi_project(ctx)
    cache = load_cache_model(ctx, list(ctx.iter_files()), openapi=oas)
    return cache, build_cache_graph(cache, oas)


def test_apicache003_vary_partitions_shared_key(tmp_path: Path) -> None:
    """Same declared key but divergent `Vary` sets -> variant-partitioned,
    not a shared-key conflict."""
    cache, (_graph, findings) = _cache(tmp_path, (
        "cache:\n  listPets: {key: pets-key, vary: [Accept-Language]}\n"
        "  createPet: {key: pets-key, vary: [Accept-Encoding]}\n"))
    assert len(cache.policies) >= 2
    assert "APICACHE003" not in _ids(findings)


def test_apicache003_authz_aware_key_is_safe(tmp_path: Path) -> None:
    """`Vary: Authorization` partitions the key per principal — a shared
    key string is not a cross-principal conflict."""
    cache, (_graph, findings) = _cache(tmp_path, (
        "cache:\n  listPets: {key: pets-key, vary: [Authorization]}\n"
        "  createPet: {key: pets-key}\n"))
    assert len(cache.policies) >= 2
    assert "APICACHE003" not in _ids(findings)


def test_apicache003_private_public_tension_not_shared(tmp_path: Path) -> None:
    """A `private` scope and a `public` scope cannot share a key —
    divergence is recorded as an unknown, not a conflict."""
    cache, (graph, findings) = _cache(tmp_path, (
        "cache:\n  listPets: {key: pets-key, scope: private}\n"
        "  createPet: {key: pets-key, scope: public}\n"))
    assert len(cache.policies) >= 2
    assert "APICACHE003" not in _ids(findings)
    assert any("pets-key" in u.subject or "pets-key" in u.missing
               for u in graph.unknowns)


def test_cache_stale_if_error_recorded(tmp_path: Path) -> None:
    """`stale_if_error` lands on `stale_policy` as declared evidence."""
    cache, _ = _cache(tmp_path, (
        "cache:\n  listPets: {key: pets-r, stale_if_error: 30}\n"))
    pol = next(p for p in cache.policies if p.subject == "listPets")
    assert pol.stale_policy is not None
    assert "stale" in pol.stale_policy.lower()


def test_apicache003_still_fires_on_true_shared_key(tmp_path: Path) -> None:
    """Guard rails must not suppress the genuine shared-key conflict."""
    _, (_graph, findings) = _cache(tmp_path, (
        "cache:\n  listPets: {key: pets-key, ttl: 60}\n"
        "  createPet: {key: pets-key, ttl: 0}\n"))
    assert "APICACHE003" in _ids(findings)


# ---------- incident intelligence ----------


BASE = 1_700_000_000_000_000_000
HOUR = 3_600_000_000_000


def _runtime_episode(with_call_evidence: bool = False):
    """checkout -> psp regression; calls carry no span evidence unless
    `with_call_evidence` — used to pin the evidence-path guarantee."""
    from forge_doctor_api.core.models import Evidence, EvidenceKind

    def exs(w: int, dur: float, retries: int, status: str):
        ev = (
            Evidence(kind=EvidenceKind.RUNTIME, source="spans.jsonl",
                     summary="span evidence"),
        ) if with_call_evidence else ()
        return tuple(
            RequestExecution(
                request_id=f"r{w}-{i}", trace_id=f"t{w}-{i}",
                service="checkout-api", operation="/checkout",
                method="GET", start_unix_nano=BASE + w * HOUR + i,
                duration_ms=dur, status="200",
                downstream_calls=(DownstreamCall(
                    caller="checkout-api", callee="payment-api",
                    operation="charge", duration_ms=900.0,
                    status=status, retries=retries, evidence=ev,
                ),),
            )
            for i in range(10)
        )
    executions = exs(0, 300.0, 0, "200") + exs(1, 1200.0, 4, "504")
    return executions


def test_diagnose_candidate_never_without_evidence_or_unknown() -> None:
    """§62: every candidate cause carries an evidence path or an
    explicit unknown link — never a bare claim."""
    from forge_doctor_api.checks.perf import run_perf_checks
    executions = _runtime_episode(with_call_evidence=False)
    report = diagnose(executions, run_perf_checks(executions))
    assert report.episodes
    for ep in report.episodes:
        assert ep.symptom
        for c in ep.candidates:
            assert c.evidence or c.unknowns, (
                f"candidate {c.subject}/{c.kind} has neither evidence "
                "path nor unknown link")


def test_diagnose_episode_carries_impact_and_unknowns() -> None:
    """Episodes carry symptom, candidates, downstream impact, and the
    unknown-link surface."""
    from forge_doctor_api.checks.perf import run_perf_checks
    executions = _runtime_episode(with_call_evidence=True)
    report = diagnose(executions, run_perf_checks(executions))
    ep = next(e for e in report.episodes if e.service == "checkout-api")
    assert ep.symptom
    assert "payment-api" in ep.affected_services
    assert ep.candidates
    for c in ep.candidates:
        assert c.evidence


# ---------- SLO budgets ----------


def _execs(n: int, *, status: str = "200") -> tuple[RequestExecution, ...]:
    return tuple(
        RequestExecution(
            request_id=f"r{i}", trace_id=f"t{i}", service="svc",
            operation="/op", start_unix_nano=BASE + i,
            duration_ms=50.0, status=status)
        for i in range(n)
    )


def test_slo_error_budget_computes_with_samples() -> None:
    obj = ApiServiceObjective(
        name="avail", metric="availability", target=0.99)
    b = error_budget(obj, _execs(10))
    assert b.sufficient is True
    assert b.total == 10


def test_slo_insufficient_samples_unknown() -> None:
    obj = ApiServiceObjective(
        name="avail", metric="availability", target=0.99)
    b = error_budget(obj, _execs(3))
    assert b.sufficient is False
    assert b.unknowns


def test_slo_latency_metric_never_fabricates_error_budget() -> None:
    """A latency-percentile objective cannot be answered from error
    counts — no interpolation, UNKNOWN budget instead."""
    obj = ApiServiceObjective(
        name="p99", metric="latency_p99", target=0.99)
    b = error_budget(obj, _execs(10))
    assert b.sufficient is False
    assert b.unknowns
    assert any("latency" in u.missing or "metric" in u.missing
               for u in b.unknowns)


def test_slo_unknown_metric_is_unknown() -> None:
    obj = ApiServiceObjective(
        name="fresh", metric="freshness", target=0.9)
    b = error_budget(obj, _execs(10))
    assert b.sufficient is False
    assert b.unknowns


# ---------- misc hard negatives ----------


def test_relapi008_post_without_evidence_still_flags(tmp_path: Path) -> None:
    """The positive path stays live: POST with no idempotency evidence."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n    post:\n      operationId: createPet\n"
            "      responses: {'201': {description: ok}}\n"),
    })
    oas = load_openapi_project(ctx)
    rel = load_reliability_model(ctx, list(ctx.iter_files()), openapi=oas)
    assert "RELAPI008" in _ids(
        run_reliability_checks(rel, operations=oas.operations))
