"""Policy file loading + §106 inheritance + §107 exception validation.

Policy files: `policies*.yaml`/`*.policy.yaml` documents with `policies:`
and `exceptions:` lists. Level comes from the file's `level:` field
(default `repo`). Inheritance: the narrowest level's policy wins for the
same rule id — but only if it does not *widen* (disable, lower severity,
looser params). Widening requires a valid exception; otherwise the wider
policy stays and a `widening` issue is recorded.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Severity
from forge_doctor_api.policy.model import (
    ApiPolicy,
    PolicyException,
    PolicyLevel,
    PolicySet,
    level_rank,
)

_POLICY_SUFFIXES = (".policy.yaml", ".policy.yml")
_POLICY_NAMES = ("policies.yaml", "policies.yml", "policy.yaml", "policy.yml")
_REQUIRED_EXCEPTION_FIELDS = (
    "rule", "scope", "owner", "justification", "created", "expires", "approval",
)


def _is_policy_file(rel: str) -> bool:
    name = Path(rel).name.lower()
    return name in _POLICY_NAMES or name.endswith(_POLICY_SUFFIXES)


def _level(value: object) -> PolicyLevel:
    try:
        return PolicyLevel(str(value))
    except ValueError:
        return PolicyLevel.REPO


def _parse_policy(raw: object, file: str, level: PolicyLevel) -> ApiPolicy | str:
    if not isinstance(raw, dict) or not raw.get("rule"):
        return f"{file}: policy entry missing `rule`"
    params = raw.get("params") or {}
    applies = raw.get("applies_to") or raw.get("applies") or "*"
    if isinstance(applies, str):
        applies = [applies]
    severity = None
    if raw.get("severity"):
        try:
            severity = Severity(str(raw["severity"]).upper())
        except ValueError:
            severity = None
    return ApiPolicy(
        id=str(raw.get("id") or f"{level.value}.{raw['rule']}"),
        rule=str(raw["rule"]),
        title=str(raw.get("title") or ""),
        level=_level(raw.get("level") or level),
        severity=severity,
        enabled=bool(raw.get("enabled", True)),
        applies_to=tuple(str(p) for p in applies),
        params=tuple(sorted((str(k), str(v)) for k, v in params.items()))
        if isinstance(params, dict) else (),
        file=file,
    )


def _parse_exception(raw: object, file: str) -> PolicyException | str:
    if not isinstance(raw, dict):
        return f"{file}: exception entry is not a mapping"
    missing = [f for f in _REQUIRED_EXCEPTION_FIELDS if not raw.get(f)]
    if missing:
        return f"{file}: exception missing fields {missing}"
    return PolicyException(
        rule=str(raw["rule"]),
        scope=str(raw["scope"]),
        owner=str(raw["owner"]),
        justification=str(raw["justification"]),
        created=str(raw["created"]),
        expires=str(raw["expires"]),
        approval=str(raw["approval"]),
        file=file,
    )


def _stronger(a: ApiPolicy, b: ApiPolicy) -> bool:
    """`a` is stronger than `b`: enabled, equal-or-higher severity, equal-or-tighter params."""
    if not a.enabled:
        return False
    rank = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    sa = rank.get(a.severity.value if a.severity else "", 2)
    sb = rank.get(b.severity.value if b.severity else "", 2)
    if sa < sb:
        return False
    pa, pb = dict(a.params), dict(b.params)
    for k, vb in pb.items():
        va = pa.get(k)
        if va is None:
            continue
        try:
            if float(va) < float(vb):
                return False
        except ValueError:
            pass
    return True


def resolve_policies(
    policies: tuple[ApiPolicy, ...],
    exceptions: tuple[PolicyException, ...],
    today: date,
) -> tuple[tuple[ApiPolicy, ...], tuple[str, ...]]:
    """§106 resolve inheritance: narrowest level wins unless it widens.

    Returns (effective policies, widening issues).
    """
    issues: list[str] = []
    by_rule: dict[str, list[ApiPolicy]] = {}
    for p in policies:
        by_rule.setdefault(p.rule, []).append(p)

    effective: list[ApiPolicy] = []
    for rule, group in sorted(by_rule.items()):
        group.sort(key=lambda p: level_rank(p.level))
        widest, narrowest = group[0], group[-1]
        if narrowest is widest:
            effective.append(widest)
            continue
        if _stronger(narrowest, widest):
            effective.append(narrowest)
            continue
        # narrowing attempt widens the rule — needs a valid exception
        exc = next(
            (e for e in exceptions if e.rule == rule and valid_exception(e, today)),
            None,
        )
        if exc is not None:
            effective.append(narrowest)
            continue
        issues.append(
            f"policy `{rule}` narrowed scope widens the {widest.level.value} "
            f"policy without a valid exception — {widest.level.value} policy kept "
            f"({narrowest.file})"
        )
        effective.append(widest)
    return tuple(effective), tuple(issues)


def exception_validity(exc: PolicyException, today: date) -> str | None:
    """None when valid; else the reason it's invalid (§107)."""
    try:
        expires = date.fromisoformat(exc.expires[:10])
    except ValueError:
        return f"expires {exc.expires!r} is not an ISO date"
    if expires < today:
        return f"expired {exc.expires}"
    if exc.approval.strip().lower() in ("", "pending", "denied", "none"):
        return f"approval {exc.approval!r} is not approved"
    return None


def valid_exception(exc: PolicyException, today: date) -> bool:
    return exception_validity(exc, today) is None


def load_policies(context: ProjectContext, files: list[str]) -> PolicySet:
    """Load every `*.policy.yaml`/`policies.yaml` under the project."""
    policies: list[ApiPolicy] = []
    exceptions: list[PolicyException] = []
    issues: list[str] = []
    for rel in sorted(files):
        if not _is_policy_file(rel):
            continue
        try:
            text = context.read_text(rel)
        except (OSError, UnicodeDecodeError):
            issues.append(f"{rel}: unreadable")
            continue
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            issues.append(f"{rel}: invalid YAML")
            continue
        if not isinstance(doc, dict):
            issues.append(f"{rel}: not a policy document")
            continue
        level = _level(doc.get("level") or PolicyLevel.REPO)
        for raw in doc.get("policies") or ():
            parsed = _parse_policy(raw, rel, level)
            if isinstance(parsed, str):
                issues.append(parsed)
            else:
                policies.append(parsed)
        for raw in doc.get("exceptions") or ():
            parsed_exc = _parse_exception(raw, rel)
            if isinstance(parsed_exc, str):
                issues.append(parsed_exc)
            else:
                exceptions.append(parsed_exc)
    return PolicySet(
        policies=tuple(policies), exceptions=tuple(exceptions), issues=tuple(issues)
    )
