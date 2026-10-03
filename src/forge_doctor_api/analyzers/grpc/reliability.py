"""gRPC reliability evidence (§27, §44, §157, §185).

Sources are declarative only: gRPC service-config JSON/YAML fragments and
generated-stub call sites in Python. No channel or broker connections.
Production marking is config-evidence only (filename or env key) - never
assumed.
"""

from __future__ import annotations

import re
from pathlib import Path

from forge_doctor_api.analyzers.grpc.model import (
    GrpcClientCall,
    GrpcRetryPolicy,
    GrpcServiceConfig,
)
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import SourceLocation

_CONFIG_SUFFIXES = {".json", ".yaml", ".yml"}
_PROD_HINT = re.compile(r"(prod|production)", re.I)
_PROD_KEY = re.compile(
    r"(?im)^\s*[\"']?(env|environment|stage)[\"']?\s*[:=]\s*[\"']?prod", re.I
)
_MAX_ATTEMPTS = re.compile(r'["\']?maxAttempts["\']?\s*[:=]\s*(\d+)')
_MAX_HEDGES = re.compile(r'["\']?(?:maxHedges|hedgingPolicy)["\']?\s*[:=]\s*(\d+)')
_BACKOFF = re.compile(r'["\']?initialBackoff["\']?\s*[:=]\s*["\']?([\w.]+)')
_DEADLINE = re.compile(r'["\']?(timeout|deadline|deadlineMs)["\']?\s*[:=]')
_HEALTH = re.compile(r'["\']?healthCheck(Config)?["\']?\s*[:=]|grpc\.health\.v1', re.I)
_LB = re.compile(r'["\']?loadBalancing(Policy|Config)["\']?\s*[:=]')
_WFR = re.compile(r'["\']?waitForReady["\']?\s*[:=]\s*true', re.I)
_KEEPALIVE = re.compile(r'["\']?keepalive\w*["\']?\s*[:=]', re.I)

_STUB_CTOR = re.compile(r"\b(\w+)Stub\s*\(")
_STUB_CALL = re.compile(r"\b(\w+)\.(\w+)\s*\(([^)]*)\)")
_KWARG = re.compile(r"\b(timeout|deadline|deadline_ms|wait_for_ready|metadata)\s*=")


def extract_service_configs(
    context: ProjectContext, files: list[str]
) -> tuple[GrpcServiceConfig, ...]:
    """Collect §27 evidence from config files mentioning gRPC keys."""
    out: list[GrpcServiceConfig] = []
    for path in sorted(files):
        if Path(path).suffix.lower() not in _CONFIG_SUFFIXES:
            continue
        try:
            text = context.read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        hits = {
            "retry": _MAX_ATTEMPTS.search(text),
            "hedge": _MAX_HEDGES.search(text),
            "deadline": _DEADLINE.search(text),
            "health": _HEALTH.search(text),
            "lb": _LB.search(text),
            "wfr": _WFR.search(text),
            "keepalive": _KEEPALIVE.search(text),
        }
        if not any(hits.values()):
            continue
        retries: list[GrpcRetryPolicy] = []
        for m in _MAX_ATTEMPTS.finditer(text):
            line = text[: m.start()].count("\n") + 1
            hedges = _MAX_HEDGES.search(text[m.end():])
            backoff = _BACKOFF.search(text[m.end():])
            retries.append(
                GrpcRetryPolicy(
                    max_attempts=int(m.group(1)),
                    max_hedges=int(hedges.group(1)) if hedges else None,
                    initial_backoff=backoff.group(1) if backoff else None,
                    location=SourceLocation(path=path, line=line),
                )
            )
        production = bool(_PROD_HINT.search(path) or _PROD_KEY.search(text))
        out.append(
            GrpcServiceConfig(
                path=path,
                production=production,
                has_health_check=bool(hits["health"]),
                retry_policies=tuple(retries),
                has_hedging=bool(hits["hedge"]),
                has_load_balancing=bool(hits["lb"]),
                has_wait_for_ready=bool(hits["wfr"]),
                has_keepalive=bool(hits["keepalive"]),
                has_deadline=bool(hits["deadline"]),
                location=SourceLocation(path=path),
            )
        )
    return tuple(out)


def extract_stub_calls(
    context: ProjectContext, files: list[str]
) -> tuple[GrpcClientCall, ...]:
    """§185: detect generated-stub construction and calls in Python source."""
    out: list[GrpcClientCall] = []
    for path in sorted(files):
        if not path.endswith(".py"):
            continue
        try:
            text = context.read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        stubs = {m.group(1).removesuffix("Stub") for m in _STUB_CTOR.finditer(text)}
        if not stubs:
            continue
        var_stub: dict[str, str] = {}
        for m in re.finditer(r"(\w+)\s*=\s*(\w+)Stub\s*\(", text):
            var_stub[m.group(1)] = m.group(2)
        for m in _STUB_CALL.finditer(text):
            var, method, args = m.group(1), m.group(2), m.group(3)
            service = var_stub.get(var)
            if service is None:
                continue
            kwargs = set(_KWARG.findall(args))
            out.append(
                GrpcClientCall(
                    stub=service,
                    method=method,
                    has_deadline=bool(kwargs & {"timeout", "deadline", "deadline_ms"}),
                    has_wait_for_ready="wait_for_ready" in kwargs,
                    location=SourceLocation(
                        path=path, line=text[: m.start()].count("\n") + 1
                    ),
                )
            )
    return tuple(out)
