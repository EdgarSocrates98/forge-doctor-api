# Knowledge packs

Mutable standards and platform facts live in **bundled versioned YAML
packs** under `src/forge_doctor_api/knowledge/` — not in code constants.
Packs ship inside the wheel and are validated at load time.

## Pack shape

```yaml
pack: openapi-versions
version: "2026.10"
domain: openapi
entries:
  - key: "3.1"
    source: "https://spec.openapis.org/oas/v3.1.0"   # provenance (§127)
    source_version: "3.1.0"
    last_verified: "2026-10-01"
    effective_since: "2021-02-15"     # optional
    deprecated_since: null            # optional
    fields: { ... }
```

Every entry requires `source`, `source_version`, `last_verified`;
malformed or stale-provenance entries fail loading loudly. Bundled
packs: `openapi-versions`, `asyncapi-versions`, `graphql-spec`,
`grpc-behaviors`, `http-semantics`, `jsonschema-dialects`,
`owasp-api-security-top-10` (edition `2023`), platform capability packs
(`fastapi`, `express`, `spring`, `aws-api-gateway`, `envoy`, `kong`,
`nginx`), and `gateway-capability-map`.

`knowledge_versions()` returns the `{pack: version}` map embedded in
every export — a finding is always attributable to the pack edition that
produced it.

## Capability detection (§69–70)

`detect_capabilities(model-set, packs)` combines evidence and pack
declarations:

- OpenAPI version features, webhooks, idempotency metadata.
- GraphQL subscription roots.
- gRPC streaming, hedging, health checks, client calls.
- AsyncAPI documents and protocol evidence.
- Reliability: retry, idempotency, health endpoints.
- Security: mTLS, rate limiting.

`CapabilityReport` verdicts are evidence-backed:
`PRESENT` / `ABSENT` / `PARTIAL` / `UNKNOWN`. Dependency rules surface
gaps (e.g. retry evidence without idempotency evidence → `SAFE_RETRY`
missing). Gap severity is informational, never a verdict on intent.

## Plugin SDK and trust boundary (§202)

`plugins/` defines `Protocol`s — `FrameworkAdapter`, `RuntimeAdapter`,
`CheckSuite` — and a `TrustClass` taxonomy:

| Trust class | Allowed |
|---|---|
| `BUILTIN` | Registered adapters shipped with the engine (e.g. FastAPI). |
| `LOCAL_TRUSTED` | Local adapters the operator has vetted. |
| `UNTRUSTED` | **Described only** — parsed statically for metadata (`describe_untrusted`), never imported or executed. |

This keeps third-party plugin code out of the engine process entirely.

## Pack lifecycle (spec 064)

External packs declare a `forge-doctor-knowledge.toml` manifest:

```toml
[knowledge]
id = "acme-rules"           # slug, required
version = "1.2.0"           # semver, required
doctor_compat = ">=0.1,<0.3"  # semver range, optional
provides = ["security"]
requires = []
```

`knowledge/manifest.py` parses strictly — malformed manifests produce
listed errors and never partially load. A stdlib semver-range parser
(`>=`, `<=`, `>`, `<`, `==`, `!=`, comma-separated) checks the pack
against the engine version; incompatible packs are skipped, listed in
`knowledge list` with status `skipped-incompatible`, and recorded as
an `UnknownFact`.

Precedence: explicit dirs > project `.forge-doctor/knowledge/` >
builtin. The builtin pack is always listed, pinned to the engine
version. A duplicate id is a `conflict-shadowed` listing — the first
entry in precedence order wins deterministically with a warning.
