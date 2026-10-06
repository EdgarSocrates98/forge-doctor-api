from __future__ import annotations

import json

import pytest

from forge_doctor_api.core.models import (
    Confidence,
    Entity,
    Evidence,
    EvidenceKind,
    Finding,
    Severity,
    SourceLocation,
    UnknownFact,
)
from forge_doctor_api.core.redaction import MASK, is_sensitive_key, redact, redact_text

SECRETS = (
    "s3cr3t-Bearer-abcdef123456",
    "hunter2-pass",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "sess-cookie-9f8e7d",
    "apikey-777-zzz",
    "cs-0a1b2c3d",
    "rt-55aa66bb",
)


@pytest.mark.parametrize(
    "key",
    [
        "Authorization",
        "authorization",
        "Proxy-Authorization",
        "Cookie",
        "Set-Cookie",
        "X-API-Key",
        "x_api_key",
        "api_key",
        "client_secret",
        "access_token",
        "refresh_token",
        "id_token",
        "github_token",
        "password",
        "db_password",
        "passwd",
        "pwd",
        "token",
        "secret",
    ],
)
def test_sensitive_keys_detected(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize(
    "key",
    ["tokens", "token_endpoint", "token_count", "user", "path", "severity", "cookie_policy_url"],
)
def test_non_sensitive_keys_kept(key: str) -> None:
    assert not is_sensitive_key(key)


def test_nested_structures_redacted_by_key() -> None:
    payload = {
        "request": {
            "headers": {
                "Authorization": "Bearer s3cr3t-Bearer-abcdef123456",
                "Cookie": "session=sess-cookie-9f8e7d",
                "Accept": "application/json",
            },
            "body": [
                {"client_secret": SECRETS[5], "user": "bob"},
                ("x", {"pwd": SECRETS[1]}),
            ],
        },
        "credentials": {"refresh_token": "rt-55aa66bb", "X-API-Key": "apikey-777-zzz"},
        "empty": {"password": None, "token": ""},
        "count": 3,
    }
    redacted = redact(payload)
    assert redacted["request"]["headers"]["Authorization"] == MASK
    assert redacted["request"]["headers"]["Cookie"] == MASK
    assert redacted["request"]["headers"]["Accept"] == "application/json"
    assert redacted["request"]["body"][0] == {"client_secret": MASK, "user": "bob"}
    assert redacted["request"]["body"][1] == ("x", {"pwd": MASK})
    assert redacted["credentials"] == {"refresh_token": MASK, "X-API-Key": MASK}
    assert redacted["empty"] == {"password": None, "token": ""}
    assert redacted["count"] == 3
    dumped = json.dumps(redacted)
    for secret in SECRETS:
        assert secret not in dumped
    assert payload["credentials"]["refresh_token"] == "rt-55aa66bb"  # input untouched


def test_sensitive_key_masks_whole_subtree() -> None:
    assert redact({"secret": {"nested": "value", "n": 1}}) == {"secret": MASK}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Authorization: Bearer abc.def.ghi", f"Authorization: {MASK}"),
        ("authorization:Basic dXNlcjpwYXNz", f"authorization:{MASK}"),
        ("Set-Cookie: sid=1; HttpOnly; Secure", f"Set-Cookie: {MASK}"),
        ("Cookie: a=1; b=2\nAccept: */*", f"Cookie: {MASK}\nAccept: */*"),
        ("X-API-Key: apikey-777-zzz", f"X-API-Key: {MASK}"),
        ("sent header Authorization: Bearer xyz", f"sent header Authorization: {MASK}"),
        ("password=hunter2 user=bob", f"password={MASK} user=bob"),
        ('{"password": "hunter two", "user": "bob"}', f'{{"password": "{MASK}", "user": "bob"}}'),
        ("client_secret: 'abc def'", f"client_secret: '{MASK}'"),
        (
            "https://api.example.com/cb?access_token=tok123&state=ok",
            f"https://api.example.com/cb?access_token={MASK}&state=ok",
        ),
        (
            "https://api.example.com/cb?state=ok&refresh_token=rt-1&api_key=k1",
            f"https://api.example.com/cb?state=ok&refresh_token={MASK}&api_key={MASK}",
        ),
        (
            "postgres://admin:hunter2-pass@db.internal:5432/app",
            f"postgres://admin:{MASK}@db.internal:5432/app",
        ),
        ("call with Bearer s3cr3t-Bearer-abcdef123456 now", f"call with Bearer {MASK} now"),
        (f"jwt {SECRETS[2]} end", f"jwt {MASK} end"),
    ],
)
def test_text_redaction(text: str, expected: str) -> None:
    assert redact_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Bearer authentication is required",
        "operation lacks a token_endpoint",
        "GET /payments/{id} returns 200",
        "tokens: 5",
        "https://api.example.com/v1/users?page=2",
        "",
    ],
)
def test_benign_text_unchanged(text: str) -> None:
    assert redact_text(text) == text


@pytest.mark.parametrize(
    "value",
    [
        "Authorization: Bearer abc",
        "https://x.test/?token=a&password=b",
        {"Cookie": "a", "list": ["password=x"]},
        "postgres://u:p@h/db",
    ],
)
def test_redaction_is_idempotent(value: object) -> None:
    once = redact(value)
    assert redact(once) == once


def test_finding_fields_redacted_at_construction() -> None:
    finding = Finding(
        id="APISEC001",
        title="Token leaked: access_token=tok-123",
        description="Example request sends Authorization: Bearer s3cr3t-Bearer-abcdef123456",
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        evidence=(
            Evidence(
                kind=EvidenceKind.STATIC,
                source="https://api.test/spec?api_key=apikey-777-zzz",
                summary="example header X-API-Key: apikey-777-zzz",
            ),
        ),
        source_location=SourceLocation(path="examples/req.http", line=3),
        remediation="rotate client_secret=cs-0a1b2c3d and remove it",
        unknowns=(
            UnknownFact(
                subject="cookie",
                missing="whether Cookie: sess-cookie-9f8e7d is still valid",
                resolution="provide gateway session config",
            ),
        ),
    )
    assert finding.title == f"Token leaked: access_token={MASK}"
    assert finding.description == f"Example request sends Authorization: {MASK}"
    assert finding.remediation == f"rotate client_secret={MASK} and remove it"
    assert finding.evidence[0].source == f"https://api.test/spec?api_key={MASK}"
    assert finding.evidence[0].summary == f"example header X-API-Key: {MASK}"
    assert finding.unknowns[0].missing == f"whether Cookie: {MASK}"
    serialized = finding.to_json()
    for secret in (*SECRETS, "tok-123"):
        assert secret not in serialized


def test_serialized_output_redacted_for_any_model() -> None:
    entity = Entity(
        id="service:http:payments",
        kind="service",
        name="payments",
        attributes={"Authorization": "Bearer raw", "base_url": "https://x.test/?token=raw-tok"},
    )
    data = entity.to_dict()
    assert data["attributes"] == {
        "Authorization": MASK,
        "base_url": f"https://x.test/?token={MASK}",
    }
    assert "raw" not in entity.to_json()
