"""Security intelligence model (§48-57, §115-120, §124-125).

Passive only: every record is derived from contract, config, or runtime
artifacts. Findings classify as candidate / configuration risk /
evidence-backed issue / unknown (§49) - static analysis NEVER yields
"vulnerability confirmed" (§50, §229).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import (
    Evidence,
    Model,
    SourceLocation,
    UnknownFact,
)

SECURITY_MODEL_SCHEMA_VERSION = "security-model/1"


class FindingClass(StrEnum):
    """§49 four-level security finding classification."""

    CANDIDATE = "candidate"
    CONFIGURATION_RISK = "configuration risk"
    EVIDENCE_BACKED = "evidence-backed issue"
    UNKNOWN = "unknown"


class AuthSchemeType(StrEnum):
    """§51 authentication scheme types."""

    OAUTH2 = "OAuth2"
    OIDC = "OIDC"
    JWT = "JWT"
    API_KEY = "API_KEY"
    BASIC = "BASIC"
    MTLS = "MTLS"
    SESSION = "SESSION"
    CUSTOM = "CUSTOM"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, kw_only=True)
class AuthenticationScheme(Model):
    """§51 a declared or observed authentication scheme."""

    name: str
    type: AuthSchemeType = AuthSchemeType.UNKNOWN
    plane: str = "contract"  # contract | implementation | gateway
    location_in: str | None = None  # header | query | cookie
    parameter_name: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class AuthorizationPolicy(Model):
    """§52 an authorization policy attached to an operation/scope."""

    operation: str  # operation identity or config scope
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    ownership_check: bool | None = None
    plane: str = "contract"
    # mechanism name when evidence is an applied mechanism (middleware /
    # dependency) rather than declared roles/scopes — evidence only,
    # never a fabricated role name.
    via: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class AuthDrift(Model):
    """§53 a disagreement between the three auth evidence planes."""

    operation: str
    contract_secured: bool | None
    impl_secured: bool | None
    gateway_secured: bool | None
    detail: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class AuthChainLink(Model):
    """§51-53 per-operation auth chain record.

    `scheme_declared`: contract scheme names resolved for the op
    (sorted, comma-joined) — None when no contract requirement lands.
    `enforcement_point`: which plane evidences enforcement —
    `"implementation"`, `"gateway"`, `"contract-only"` (declared but
    no enforcement plane answers), or `"none"`.
    `chain_complete`: True when a declared scheme reaches an
    enforcement plane; False = a chain break (declared-but-unenforced,
    or enforced-but-undeclared); None = evidence insufficient.
    """

    operation: str
    scope: str
    scheme_declared: str | None = None
    enforcement_point: str = "none"
    chain_complete: bool | None = None
    evidence_refs: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class RateLimitPolicy(Model):
    """§54 declared rate-limit policy."""

    scope: str
    limit: float | None = None
    window: str | None = None
    burst: float | None = None
    key: str | None = None
    location: SourceLocation | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class CorsPolicy(Model):
    """§55 CORS policy - modeled without simplification."""

    scope: str
    allowed_origins: tuple[str, ...] = ()
    credentials: bool | None = None
    methods: tuple[str, ...] = ()
    headers: tuple[str, ...] = ()
    wildcard: bool = False
    location: SourceLocation | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class TlsEvidence(Model):
    """§56 TLS/mTLS configuration evidence - detection only."""

    scope: str
    kind: str  # tls | mtls
    detail: str | None = None
    evidence: tuple[Evidence, ...] = ()


class PaginationKind(StrEnum):
    """§118 pagination kinds."""

    OFFSET = "offset"
    CURSOR = "cursor"
    KEYSET = "keyset"
    TOKEN = "token"
    NONE = "none"


@dataclass(frozen=True, kw_only=True)
class PaginationModel(Model):
    """§118 pagination evidence for one operation."""

    operation: str
    kind: PaginationKind = PaginationKind.NONE
    bounded: bool | None = None
    limit_param: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class WebhookModel(Model):
    """§117 webhook receiver/publisher evidence."""

    name: str
    direction: str = "unknown"  # inbound | outbound | unknown
    signature_verification: bool | None = None
    replay_protection: bool | None = None
    idempotency: bool | None = None
    retry: bool | None = None
    evidence: tuple[Evidence, ...] = ()


class DataCategory(StrEnum):
    """§124 explicit data-classification categories."""

    PII = "PII"
    CREDENTIAL = "credential"
    FINANCIAL = "financial"
    HEALTH = "health"
    INTERNAL = "internal"


@dataclass(frozen=True, kw_only=True)
class DataClassification(Model):
    """§124 classification - ONLY from explicit metadata, never inferred."""

    subject: str  # schema property / operation pointer
    category: DataCategory
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ExternalApi(Model):
    """§115 a declared third-party API dependency."""

    host: str
    operations: tuple[str, ...] = ()
    timeout_ms: float | None = None
    has_retry: bool | None = None
    has_auth: bool | None = None
    owner: str | None = None
    criticality: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class SensitiveBusinessFlow(Model):
    """§120 a business-flow protection record - declared evidence only."""

    name: str
    description: str | None = None
    protections: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()


class GatewayPolicyAdapter(ABC):
    """Reserved seam for gateway-specific policy extraction.

    No live gateway integration ships - adapters parse config artifacts
    when added.
    """

    name: str

    @abstractmethod
    def detect(self, path: str, head: bytes) -> bool:
        """Strong-marker detection on a config artifact."""


@dataclass(frozen=True, kw_only=True)
class ApiSecurityModel(Model):
    """§48 aggregated passive security evidence for a project."""

    auth_schemes: tuple[AuthenticationScheme, ...] = ()
    authorization: tuple[AuthorizationPolicy, ...] = ()
    auth_drift: tuple[AuthDrift, ...] = ()
    auth_chain: tuple[AuthChainLink, ...] = ()
    rate_limits: tuple[RateLimitPolicy, ...] = ()
    cors: tuple[CorsPolicy, ...] = ()
    tls: tuple[TlsEvidence, ...] = ()
    webhooks: tuple[WebhookModel, ...] = ()
    pagination: tuple[PaginationModel, ...] = ()
    classifications: tuple[DataClassification, ...] = ()
    external_apis: tuple[ExternalApi, ...] = ()
    business_flows: tuple[SensitiveBusinessFlow, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
