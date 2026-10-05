"""Reliability config extraction (§40-46, §156-158).

Reads declared configuration from YAML/JSON artifacts - Envoy-style
gateway config, Resilience4j blocks, gRPC service configs (reused from
spec 013) - and Python stub-call kwargs. Weak keyword hints never
fabricate policies; every record cites its file/line.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from forge_doctor_api.analyzers.grpc.reliability import (
    extract_service_configs,
    extract_stub_calls,
)
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Evidence, EvidenceKind, SourceLocation
from forge_doctor_api.reliability.idempotency import aggregate_idempotency
from forge_doctor_api.reliability.model import (
    ApiReliabilityModel,
    ApiServiceObjective,
    CircuitBreakerConfig,
    GracefulShutdownEvidence,
    HealthCheckEvidence,
    IdempotencySource,
    LoadBalancing,
    LoadBalancingKind,
    RetryPolicy,
    TimeoutConfig,
)

_CONFIG_SUFFIXES = {".yaml", ".yml", ".json"}
_MS = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m)?\s*$")
_LB_MAP = {
    "round_robin": LoadBalancingKind.ROUND_ROBIN,
    "roundrobin": LoadBalancingKind.ROUND_ROBIN,
    "least_request": LoadBalancingKind.LEAST_REQUEST,
    "leastrequest": LoadBalancingKind.LEAST_REQUEST,
    "least_conn": LoadBalancingKind.LEAST_REQUEST,
    "pick_first": LoadBalancingKind.PICK_FIRST,
    "pickfirst": LoadBalancingKind.PICK_FIRST,
    "weighted": LoadBalancingKind.WEIGHTED,
    "ring_hash": LoadBalancingKind.WEIGHTED,
    "maglev": LoadBalancingKind.WEIGHTED,
}
_RETRY_KEYS = ("retry_policy", "retryPolicy", "retry", "retries",
               "attempts")
_TIMEOUT_KEYS = ("per_try_timeout", "perTryTimeout", "timeout",
                 "connect_timeout", "connectTimeout",
                 "upstream_rq_timeout", "request_timeout", "deadline")
_CB_KEYS = ("circuit_breakers", "circuitBreakers", "outlier_detection",
            "circuitbreaker")
_HEALTH_KEYS = ("health_checks", "healthChecks", "health_check",
                "healthCheck")
_SHUTDOWN_KEYS = ("drain_listeners", "parent_shutdown_time_ms",
                  "graceful_shutdown", "shutdown")
_SLO_KEYS = ("slo", "slos", "objectives", "serviceObjectives")
_NAME_KEYS = ("scope", "subject", "name", "cluster", "cluster_name",
              "route", "route_config", "virtual_host", "service")
_IDEM_KEYS = ("idempotency", "idempotent", "x_idempotent", "xIdempotent")
# Keys whose subtrees carry documentation/sample/schema content, never
# declared policy (OpenAPI `examples`, schema `properties`, narrative
# fields). The walker must not descend into them — a `retries: 5`
# inside an example is not a retry policy (spec 088).
_NON_EVIDENCE_KEYS = frozenset({
    "example", "examples", "description", "documentation", "docs",
    "comment", "comments", "note", "notes", "summary", "default",
    "properties", "schema", "schemas", "items", "definitions",
    "components", "value", "content", "requestbody", "responses",
    "parameters", "headers", "allof", "anyof", "oneof", "enum",
})


def _ms(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = _MS.match(value)
        if m:
            v = float(m.group(1))
            unit = m.group(2)
            return v * 60000 if unit == "m" else v * 1000 if unit == "s" else v
    return None


def _ev(path: str, line: int | None, summary: str) -> tuple[Evidence, ...]:
    return (
        Evidence(
            kind=EvidenceKind.CONFIG,
            source=path,
            summary=summary,
            line=line,
        ),
    )


def _line_of(text: str, needle: str) -> int | None:
    i = text.find(needle)
    return text[:i].count("\n") + 1 if i >= 0 else None


def _nearest_name(node: Any, trail: tuple[str, ...]) -> str | None:
    """Best-effort scope name: `name:` on the node, else last path key."""
    if isinstance(node, dict):
        for k in _NAME_KEYS:
            v = node.get(k)
            if isinstance(v, str) and v:
                return v
    for k in reversed(trail):
        if k not in _RETRY_KEYS + _TIMEOUT_KEYS + _CB_KEYS + _IDEM_KEYS:
            return k
    return None


def _walk(
    node: Any,
    path: str,
    trail: tuple[str, ...],
    out: dict[str, list[Any]],
    text: str,
    parent_name: str | None = None,
    structural: bool = False,
) -> None:
    if not isinstance(node, dict):
        return
    low_keys = {str(k).lower(): k for k in node}
    node_name = next(
        (str(node[k]) for k in _NAME_KEYS
         if isinstance(node.get(k), str) and node.get(k)),
        None,
    )

    def get(*names: str) -> Any:
        for n in names:
            if n.lower() in low_keys:
                return node[low_keys[n.lower()]]
        return None

    consumed: Any = None
    retry = get("retry_policy", "retryPolicy", "retries")
    if isinstance(retry, dict):
        attempts = _num(
            retry.get("num_retries")
            or retry.get("numRetries")
            or retry.get("maxAttempts")
            or retry.get("max_attempts")
            or retry.get("attempts")
        )
        statuses = (
            retry.get("retry_on") or retry.get("retryOn")
            or retry.get("retryable_statuses")
        )
        scope = str(
            retry.get("scope") or retry.get("name")
            or _nearest_name(node, ()) or parent_name
            or _nearest_name(node, trail) or Path(path).stem)
        out["retries"].append(
            RetryPolicy(
                scope=str(scope),
                max_attempts=attempts,
                backoff=str(retry.get("backoff") or "") or None,
                retryable_statuses=(
                    tuple(str(s) for s in str(statuses).split(","))
                    if statuses
                    else ()
                ),
                location=SourceLocation(
                    path=path, line=_line_of(text, "retry")
                ),
                evidence=_ev(path, _line_of(text, "retry"),
                             f"retry policy at {scope}"),
            )
        )
        consumed = retry
    # scalar attempts keys - suppressed inside a `retries:`/`retry:`
    # body already consumed by the dict branch above (no double count);
    # a `retries:` *list* of policy records is not a body, so its items
    # still reach this branch.
    attempts = _num(get("num_retries", "numRetries", "maxAttempts",
                        "max_attempts", "retries"))
    if (attempts is not None and not isinstance(retry, dict)
            and not structural):
        scope = _nearest_name(node, trail) or Path(path).stem
        out["retries"].append(
            RetryPolicy(
                scope=str(scope),
                max_attempts=attempts,
                location=SourceLocation(
                    path=path, line=_line_of(text, "retries")
                ),
                evidence=_ev(path, _line_of(text, "retries"),
                             f"retry attempts at {scope}"),
            )
        )

    for tk in _TIMEOUT_KEYS:
        raw = get(tk)
        ms = _ms(raw)
        if ms is not None:
            # Inside a structural block (a consumed `retries:`/`retry:`
            # body or an idempotency block) the declared name lives on
            # the parent node - e.g. Istio `retries: {attempts,
            # perTryTimeout}` under a named route.
            scope = str(
                _nearest_name(node, ())
                or (parent_name if structural else None)
                or _nearest_name(node, trail)
                or Path(path).stem)
            out["timeouts"].append(
                TimeoutConfig(
                    scope=str(scope),
                    timeout_ms=ms,
                    location=SourceLocation(
                        path=path, line=_line_of(text, tk)
                    ),
                    evidence=_ev(path, _line_of(text, tk),
                                 f"timeout at {scope}"),
                )
            )
            break

    for ck in _CB_KEYS:
        if get(ck) is not None:
            scope = _nearest_name(node, trail) or Path(path).stem
            provider = (
                "resilience4j"
                if "resilience4j" in trail or "resilience4j" in low_keys
                else "config"
            )
            out["cbs"].append(
                CircuitBreakerConfig(
                    scope=str(scope),
                    provider=provider,
                    location=SourceLocation(
                        path=path, line=_line_of(text, ck)
                    ),
                    evidence=_ev(path, _line_of(text, ck),
                                 f"circuit breaker at {scope}"),
                )
            )
            break

    lb = get("lb_policy", "lbPolicy", "loadBalancingPolicy",
             "load_balancing_policy")
    if lb is not None:
        scope = _nearest_name(node, trail) or Path(path).stem
        kind = _LB_MAP.get(str(lb).lower().replace("-", "_"),
                           LoadBalancingKind.CUSTOM)
        out["lbs"].append(
            LoadBalancing(
                scope=str(scope),
                kind=kind,
                detail=str(lb),
                evidence=_ev(path, _line_of(text, "lb_policy"),
                             f"lb {lb} at {scope}"),
            )
        )

    for hk in _HEALTH_KEYS:
        if get(hk) is not None:
            scope = _nearest_name(node, trail) or Path(path).stem
            proto = (
                "grpc-health-v1" if "grpc" in text.lower() else "config"
            )
            out["health"].append(
                HealthCheckEvidence(
                    scope=str(scope),
                    protocol=proto,
                    evidence=_ev(path, _line_of(text, hk),
                                 f"health check at {scope}"),
                )
            )
            break

    idem = get("idempotency", "idempotent", "x_idempotent", "xIdempotent")
    in_idem_block = any(t in _IDEM_KEYS for t in trail)
    if (idem is not None and not isinstance(idem, dict)) or in_idem_block:
        block_key = next(
            (t for t in reversed(trail) if t in _IDEM_KEYS), None
        )
        if block_key is None and isinstance(node, dict):
            block_key = next(
                (str(k) for k in node
                 if str(k).lower() in {k.lower() for k in _IDEM_KEYS}),
                None,
            )
        block_ev = _ev(
            path, _line_of(text, str(block_key or "idempotency")),
            "idempotency config",
        )
        sources: list[IdempotencySource] = []
        method = get("method", "http_method")
        if method is not None:
            sources.append(
                IdempotencySource(
                    kind="http_method", detail=str(method), supports=None,
                    evidence=block_ev,
                )
            )
        key = get("key_header", "idempotency_key", "idempotencyKey",
                  "x_idempotency_key")
        if key is not None:
            sources.append(
                IdempotencySource(
                    kind="idempotency_key",
                    detail=str(key) if isinstance(key, str) else "present",
                    supports=True,
                    evidence=block_ev,
                )
            )
        declared = get("idempotent", "declared", "x_idempotent")
        if isinstance(idem, bool):
            declared = idem
        if isinstance(declared, bool):
            sources.append(
                IdempotencySource(
                    kind="contract_metadata",
                    detail=f"declared idempotent={declared}",
                    supports=declared,
                    evidence=block_ev,
                )
            )
        uniq = get("unique_constraint", "db_uniqueness")
        if uniq is not None:
            sources.append(
                IdempotencySource(
                    kind="db_uniqueness",
                    detail=str(uniq) if isinstance(uniq, str) else "present",
                    supports=True,
                    evidence=block_ev,
                )
            )
        subject = str(
            _nearest_name(node, ())
            or (parent_name if in_idem_block else None)
            or _nearest_name(node, trail)
            or Path(path).stem
        )
        out["idem"].append(
            aggregate_idempotency(subject, tuple(sources))
        )

    for sk in _SHUTDOWN_KEYS:
        raw = get(sk)
        if raw is not None:
            scope = _nearest_name(node, trail) or Path(path).stem
            out["shutdown"].append(
                GracefulShutdownEvidence(
                    scope=str(scope),
                    signal=sk,
                    drain_seconds=_ms(raw),
                    evidence=_ev(path, _line_of(text, sk),
                                 f"shutdown evidence at {scope}"),
                )
            )
            break

    for key, val in node.items():
        if str(key).lower() in _NON_EVIDENCE_KEYS:
            continue
        ktrail = (*trail, str(key))
        if str(key) in _SLO_KEYS:
            items = val if isinstance(val, list) else [val]
            for item in items:
                if isinstance(item, dict):
                    low = {str(k).lower(): k for k in item}
                    name = item.get(low.get("name", "name"))
                    metric = item.get(low.get("metric", "metric")) or \
                        item.get(low.get("type", "type"))
                    target = item.get(low.get("target", "target")) or \
                        item.get(low.get("target_percentage",
                                         "target_percentage"))
                    if metric is not None and target is not None:
                        try:
                            tval = float(target)
                        except (TypeError, ValueError):
                            continue
                        if tval > 1.0:
                            tval = tval / 100.0
                        out["slos"].append(
                            ApiServiceObjective(
                                name=str(name or metric),
                                metric=str(metric),
                                target=tval,
                                window=(
                                    str(item[low["window"]])
                                    if "window" in low
                                    else None
                                ),
                                evidence=_ev(
                                    path,
                                    _line_of(text, str(key)),
                                    f"SLO {name or metric}",
                                ),
                            )
                        )
            continue
        if isinstance(val, dict):
            _walk(val, path, ktrail, out, text,
                  parent_name=node_name or parent_name,
                  structural=(structural or val is consumed
                              or ktrail[-1] in _IDEM_KEYS))
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    _walk(item, path, ktrail, out, text,
                          parent_name=node_name or parent_name,
                          structural=(structural
                                      or ktrail[-1] in _IDEM_KEYS))


def _num(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def load_reliability_model(
    context: ProjectContext, files: list[str],
    *, openapi: Any = None,
) -> ApiReliabilityModel:
    """Extract declared reliability evidence from config artifacts.

    `openapi` contributes operation-level `x-idempotent` /
    `x-idempotency` / `x-idempotency-key` extension evidence, bound to
    the operation's declared identifiers (operationId or identity).
    """
    out: dict[str, list[Any]] = {
        "retries": [],
        "timeouts": [],
        "cbs": [],
        "lbs": [],
        "health": [],
        "shutdown": [],
        "idem": [],
        "slos": [],
    }
    for path in sorted(files):
        if Path(path).suffix.lower() not in _CONFIG_SUFFIXES:
            continue
        try:
            text = context.read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            doc = None
        if isinstance(doc, dict):
            _walk(doc, path, (), out, text)

    # gRPC service configs + stub-call kwargs (spec 013 reuse). The
    # spec-013 extractor intentionally uses weak hints; here we require
    # a gRPC-specific marker so generic `timeout:` keys in Envoy/app
    # YAML aren't double-counted as gRPC service configs.
    _grpc_markers = (
        "methodConfig", "loadBalancingConfig", "waitForReady",
        "grpc.health", "serviceConfig", "retryThrottling",
    )
    stub_calls = extract_stub_calls(context, files)
    for cfg in extract_service_configs(context, files):
        try:
            cfg_text = context.read_text(cfg.path)
        except (OSError, UnicodeDecodeError):
            cfg_text = ""
        if not any(mk in cfg_text for mk in _grpc_markers):
            continue
        scope = Path(cfg.path).stem
        for rp in cfg.retry_policies:
            out["retries"].append(
                RetryPolicy(
                    scope=scope,
                    max_attempts=rp.max_attempts,
                    backoff=rp.initial_backoff,
                    location=rp.location,
                    evidence=_ev(cfg.path, rp.location.line
                                 if rp.location else None,
                                 f"gRPC retry policy in {cfg.path}"),
                )
            )
        if cfg.has_deadline:
            out["timeouts"].append(
                TimeoutConfig(
                    scope=scope,
                    location=SourceLocation(path=cfg.path),
                    evidence=_ev(cfg.path, None, "gRPC deadline config"),
                )
            )
        if cfg.has_health_check:
            out["health"].append(
                HealthCheckEvidence(
                    scope=scope,
                    protocol="grpc-health-v1",
                    evidence=_ev(cfg.path, None,
                                 "gRPC health protocol config"),
                )
            )
        if cfg.has_load_balancing:
            out["lbs"].append(
                LoadBalancing(
                    scope=scope,
                    kind=LoadBalancingKind.UNKNOWN,
                    evidence=_ev(cfg.path, None, "gRPC LB config"),
                )
            )
        if cfg.has_hedging:
            pass  # hedging noted on the retry policy itself
    for call in stub_calls:
        if call.has_deadline:
            out["timeouts"].append(
                TimeoutConfig(
                    scope=f"{call.stub}.{call.method}",
                    location=call.location,
                    evidence=_ev(
                        call.location.path,
                        call.location.line,
                        f"stub call deadline {call.stub}.{call.method}",
                    ),
                )
            )

    # OpenAPI x-idempotency extensions become contract-metadata or
    # idempotency-key sources bound to the operation identity (§42).
    if openapi is not None:
        op_by_pointer = {o.pointer: o for o in openapi.operations}
        by_subject: dict[str, list[IdempotencySource]] = {}
        for ext in openapi.extensions:
            op = op_by_pointer.get(ext.owner_pointer)
            if op is None:
                continue
            name = ext.name.lower().replace("_", "-")
            subject = op.operation_id or op.identity
            ev = _ev(ext.location.path, ext.location.line,
                     f"{ext.name} on {subject}")
            if name in {"x-idempotent", "xidempotent"} or (
                    name in {"x-idempotency", "x-idempotency-key"}
                    and isinstance(ext.value, bool)):
                by_subject.setdefault(subject, []).append(
                    IdempotencySource(
                        kind="contract_metadata",
                        detail=f"{ext.name}={ext.value}",
                        supports=(ext.value
                                  if isinstance(ext.value, bool) else None),
                        evidence=ev))
            elif name in {"x-idempotency-key", "x-idempotency"}:
                by_subject.setdefault(subject, []).append(
                    IdempotencySource(
                        kind="idempotency_key",
                        detail=(str(ext.value)
                                if isinstance(ext.value, str)
                                else "present"),
                        supports=True, evidence=ev))
        existing = {i.subject: i for i in out["idem"]}
        for subject, sources in sorted(by_subject.items()):
            prev = existing.get(subject)
            merged = tuple(sources) + (prev.sources if prev else ())
            agg = aggregate_idempotency(subject, merged)
            if prev is not None:
                out["idem"][out["idem"].index(prev)] = agg
            else:
                out["idem"].append(agg)

    retries = tuple(sorted(out["retries"], key=lambda r: r.scope))
    timeouts = tuple(sorted(out["timeouts"], key=lambda t: t.scope))
    cbs = tuple(sorted(out["cbs"], key=lambda c: c.scope))
    lbs = tuple(sorted(out["lbs"], key=lambda lb: lb.scope))
    health = tuple(sorted(out["health"], key=lambda h: h.scope))
    shutdown = tuple(sorted(out["shutdown"], key=lambda s: s.scope))
    return ApiReliabilityModel(
        retry_policies=retries,
        timeouts=timeouts,
        circuit_breakers=cbs,
        load_balancing=lbs,
        health_checks=health,
        shutdown_evidence=shutdown,
        idempotency=tuple(
            sorted(out["idem"], key=lambda i: i.subject)
        ),
        objectives=tuple(
            sorted(out["slos"], key=lambda o: o.name)
        ),
        evidence=(
            Evidence(
                kind=EvidenceKind.CONFIG,
                source="(project)",
                summary=f"{len(retries)} retry policies, "
                f"{len(timeouts)} timeouts, {len(cbs)} circuit breakers",
            ),
        ),
    )


def _detail_int(detail: str) -> int | None:
    """`retries=5` -> 5; anything non-numeric stays None."""
    value = detail.rsplit("=", 1)[-1].strip()
    return int(value) if value.isdigit() else None


def _detail_ms(detail: str) -> float | None:
    """`timeout=2s` -> 2000.0; absent units are read as ms."""
    return _ms(detail.rsplit("=", 1)[-1].strip())


def gateway_edge_policies(
    gateways: tuple[Any, ...],
    meshes: tuple[Any, ...],
) -> tuple[tuple[RetryPolicy, ...], tuple[TimeoutConfig, ...]]:
    """Gateway/mesh retry+timeout declarations -> edge-scoped evidence.

    A gateway retry declared on calls to upstream X is caller-side
    evidence on the `dialect->X` edge; scopes are built from declared
    identifiers only (dialect/vendor value + the entry's declared
    subject name) - never route-name similarity.
    """
    retries: list[RetryPolicy] = []
    timeouts: list[TimeoutConfig] = []
    for gw in gateways:
        prefix = gw.dialect.value
        for e in gw.retries:
            retries.append(RetryPolicy(
                scope=f"{prefix}->{e.name}",
                max_attempts=_detail_int(e.detail),
                location=e.location,
                evidence=_ev(e.location.path, e.location.line,
                             f"gateway retry ({e.detail}) on {e.name}")))
        for e in gw.timeouts:
            timeouts.append(TimeoutConfig(
                scope=f"{prefix}->{e.name}",
                timeout_ms=_detail_ms(e.detail),
                location=e.location,
                evidence=_ev(e.location.path, e.location.line,
                             f"gateway timeout ({e.detail}) on {e.name}")))
    for mesh in meshes:
        prefix = mesh.vendor.value
        for e in mesh.retries:
            retries.append(RetryPolicy(
                scope=f"{prefix}->{e.name}",
                max_attempts=_detail_int(e.detail),
                location=e.location,
                evidence=_ev(e.location.path, e.location.line,
                             f"mesh retry ({e.detail}) on {e.name}")))
        for e in mesh.timeouts:
            timeouts.append(TimeoutConfig(
                scope=f"{prefix}->{e.name}",
                timeout_ms=_detail_ms(e.detail),
                location=e.location,
                evidence=_ev(e.location.path, e.location.line,
                             f"mesh timeout ({e.detail}) on {e.name}")))
    return (
        tuple(sorted(retries, key=lambda r: r.scope)),
        tuple(sorted(timeouts, key=lambda t: t.scope)),
    )
