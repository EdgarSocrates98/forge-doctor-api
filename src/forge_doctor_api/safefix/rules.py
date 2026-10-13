"""§104 deterministic rule table — fix type -> class -> justification.

Three sources of truth:
- SAFE: metadata/doc/normalization fixes that cannot change wire behavior.
- REVIEW_REQUIRED: tunables whose change affects load/latency semantics.
- MANUAL_ONLY: anything touching auth, authorization, breaking contract
  shape, gateway routing, TLS, rate limits, or schema removal.
- default-deny: an unmapped fix type is MANUAL_ONLY, never guessed down.
"""

from __future__ import annotations

from forge_doctor_api.safefix.model import _CLASS_RANK, FixClass, FixType

# §104 member -> class (the complete three-class table)
_CLASS: dict[FixType, FixClass] = {
    FixType.METADATA_MISSING: FixClass.SAFE,
    FixType.DEPRECATED_CONFIG_RENAME: FixClass.SAFE,
    FixType.DOC_FIELD: FixClass.SAFE,
    FixType.SPEC_NORMALIZATION: FixClass.SAFE,
    FixType.TIMEOUT: FixClass.REVIEW_REQUIRED,
    FixType.RETRY: FixClass.REVIEW_REQUIRED,
    FixType.CACHE: FixClass.REVIEW_REQUIRED,
    FixType.PAGINATION_DEFAULT: FixClass.REVIEW_REQUIRED,
    FixType.AUTH: FixClass.MANUAL_ONLY,
    FixType.AUTHORIZATION: FixClass.MANUAL_ONLY,
    FixType.BREAKING_CONTRACT: FixClass.MANUAL_ONLY,
    FixType.GATEWAY_ROUTING: FixClass.MANUAL_ONLY,
    FixType.TLS: FixClass.MANUAL_ONLY,
    FixType.RATE_LIMIT: FixClass.MANUAL_ONLY,
    FixType.SCHEMA_REMOVAL: FixClass.MANUAL_ONLY,
    FixType.UNMAPPED: FixClass.MANUAL_ONLY,
}

# check id -> fix types (one row per check; missing ids fall back to
# UNMAPPED -> MANUAL_ONLY via default-deny)
_BY_CHECK: dict[str, tuple[FixType, ...]] = {
    # SAFE — explicit OpenAPI metadata / doc / normalization (§104 SAFE)
    "OAS001": (FixType.SPEC_NORMALIZATION,),
    "OAS002": (FixType.SPEC_NORMALIZATION,),
    "OAS003": (FixType.SPEC_NORMALIZATION,),
    "OAS004": (FixType.METADATA_MISSING,),
    "OAS005": (FixType.METADATA_MISSING,),
    "OAS006": (FixType.DOC_FIELD,),
    "OAS007": (FixType.SPEC_NORMALIZATION,),
    "OAS009": (FixType.DOC_FIELD,),
    "OAS014": (FixType.SPEC_NORMALIZATION,),
    "OAS015": (FixType.METADATA_MISSING,),
    "OAS018": (FixType.SPEC_NORMALIZATION,),
    "OAS020": (FixType.METADATA_MISSING,),
    # MANUAL_ONLY — contract shape / auth surface
    "OAS008": (FixType.BREAKING_CONTRACT,),   # adding request schema tightens contract
    "OAS010": (FixType.AUTH,),                # adding security requirements
    "OAS011": (FixType.AUTHORIZATION,),       # security override change
    "OAS012": (FixType.BREAKING_CONTRACT,),   # path param rename
    "OAS013": (FixType.BREAKING_CONTRACT,),   # declaring required param
    "OAS016": (FixType.GATEWAY_ROUTING,),     # server URL env change
    "OAS017": (FixType.BREAKING_CONTRACT,),   # restricting additionalProperties
    "OAS019": (FixType.BREAKING_CONTRACT,),   # schema restructure
    # MANUAL_ONLY — security surface (§104 members)
    "APISEC001": (FixType.AUTHORIZATION,),
    "APISEC002": (FixType.AUTHORIZATION,),
    "APISEC003": (FixType.AUTH,),
    "APISEC004": (FixType.AUTHORIZATION,),    # CORS is access policy
    "APISEC005": (FixType.RATE_LIMIT,),
    "APISEC006": (FixType.PAGINATION_DEFAULT, FixType.RATE_LIMIT),
    "APISEC007": (FixType.AUTHORIZATION,),
    "APISEC008": (FixType.SCHEMA_REMOVAL,),   # removing exposed property
    "APISEC009": (FixType.GATEWAY_ROUTING,),  # decommissioning traffic
    "APISEC010": (FixType.AUTH, FixType.TIMEOUT),
    # REVIEW_REQUIRED — tunables
    "RELAPI001": (FixType.RETRY,),
    "RELAPI002": (FixType.RETRY,),
    "RELAPI003": (FixType.TIMEOUT,),
    "RELAPI004": (FixType.TIMEOUT,),
    "RELAPI005": (FixType.UNMAPPED,),         # circuit breaker — not in §104 table
    "RELAPI006": (FixType.UNMAPPED,),         # health check — default-deny
    "RELAPI007": (FixType.UNMAPPED,),         # graceful shutdown — default-deny
    "APIPERF004": (FixType.RETRY,),
    "APIPERF005": (FixType.TIMEOUT,),
    "APIPERF006": (FixType.UNMAPPED,),        # payload reduction may change schema
    "APIPERF007": (FixType.UNMAPPED,),        # fan-out change is architectural
    "APIPERF008": (FixType.CACHE,),
}
# perf regressions (001-003), drift, compat, client, async/gql/grpc/obs
# findings are unmapped -> MANUAL_ONLY by default-deny.

_JUSTIFY: dict[FixType, str] = {
    FixType.METADATA_MISSING: "missing explicit contract metadata — doc-only change",
    FixType.DEPRECATED_CONFIG_RENAME: "deprecated key rename — no behavior change",
    FixType.DOC_FIELD: "documentation field — no contract semantics changed",
    FixType.SPEC_NORMALIZATION: "spec normalization — canonical form, same semantics",
    FixType.TIMEOUT: "timeout change affects latency budgets and downstream waits",
    FixType.RETRY: "retry change affects downstream load and amplification",
    FixType.CACHE: "cache change affects freshness and load distribution",
    FixType.PAGINATION_DEFAULT: "pagination default changes response size and client paging",
    FixType.AUTH: "auth change affects the credential surface",
    FixType.AUTHORIZATION: "authorization change affects who can reach what",
    FixType.BREAKING_CONTRACT: "change alters the contract consumers rely on",
    FixType.GATEWAY_ROUTING: "gateway routing change affects traffic paths",
    FixType.TLS: "TLS change affects transport security",
    FixType.RATE_LIMIT: "rate-limit change affects availability and abuse controls",
    FixType.SCHEMA_REMOVAL: "schema removal is breaking for readers",
    FixType.UNMAPPED: "fix type is not in the §104 table — default-deny MANUAL_ONLY",
}


def classify_types(fix_types: tuple[FixType, ...]) -> FixClass:
    """Combined fixes escalate to the strictest class (§104)."""
    if not fix_types:
        return FixClass.MANUAL_ONLY
    return max((_CLASS[t] for t in fix_types), key=lambda c: _CLASS_RANK[c])


def justification(fix_types: tuple[FixType, ...]) -> str:
    """Justification text generated from the rule table, not free-form."""
    types = fix_types or (FixType.UNMAPPED,)
    return "; ".join(dict.fromkeys(_JUSTIFY[t] for t in types))


def fix_types_for(check_id: str) -> tuple[FixType, ...]:
    """Map a finding's check id to fix types; unknown ids -> UNMAPPED."""
    return _BY_CHECK.get(check_id, (FixType.UNMAPPED,))
