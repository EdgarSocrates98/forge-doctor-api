# Multi-repo workspaces and fleet intelligence

## Workspace manifest

`forge-doctor-api.workspace.yaml` declares member repositories —
nothing is discovered by scanning the filesystem:

```yaml
name: payments-platform
members:
  - name: payments-api
    path: ../payments-api
    role: service            # service | client | gateway | contracts | mixed
    provides: [payments-sdk] # package names this repo publishes
  - name: payments-sdk
    path: ../payments-sdk
    role: client
  - name: checkout
    path: ../checkout
    role: service
```

Rules:

- Absent manifest → the directory is treated as a single repo, not a
  workspace.
- Roles are **declared or `UNKNOWN`** — never inferred from layout.
  A missing member path is listed in `members_missing` + `unknowns`.
- Member paths resolve through `ProjectContext`; `..` escapes outside
  the workspace root are rejected.
- Duplicate member names: first wins + a recorded issue.

## Per-repo scan, then link

Each member is scanned by role (`service`/`contracts`/`mixed` → OpenAPI
ops, `client`/`mixed` → call sites, `gateway`/`mixed` → routes), then
cross-repo edges are resolved:

| Edge | Evidence |
|---|---|
| `CLIENT_CALLS` | Client call site ↔ operation, template-aware path matching. |
| `CONTRACT_IMPLEMENTS` | Same normalized method+path in two repos. |
| `GATEWAY_ROUTES` | Gateway route exactly covers or prefixes an operation path. |
| `SDK_CONSUMED_BY` | Import statements matching declared `provides` names. |

`resolve_chains` emits all simple ≥2-hop paths
(`checkout → payments-sdk → payments-api`), each hop carrying aggregated
edge evidence.

## `inventory` — the six fleet questions

```bash
forge-doctor-api inventory ./workspace-root [--json]
```

| Question | Answer shape |
|---|---|
| Public APIs | Operations with public markers, per repo. |
| Unowned APIs | APIs where ownership resolution found nothing — *the absence is the answer*. |
| Unauthenticated operations | Ops without auth evidence. |
| Deprecated versions | Deprecated ops + remaining callers. |
| Regressing endpoints | APIPERF findings when runtime evidence exists; UNKNOWN when absent. |
| Shared external APIs | External hosts consumed by ≥2 repos. |

Plus `PlatformPortfolio` (per-member protocol styles and counts),
`ComplexitySignal`s (multi-protocol members, shared external
dependencies, gateway chains ≥2 hops, multiple auth models),
`DeprecationReadiness` (remaining clients — distinguishing "no client
repos" `None` from "0 matching call sites" — observed traffic, contract
age, replacement/sunset), `ApiQualityModel` per-dimension evidence, and
`fleet_health_counts` (breaking/reliability/security/runtime/unknown).

No composite score is computed — §191 keeps dimensions separate.

## Measured fact set — no scores

`inventory` reports **facts per member repo**, never invented health
metrics or rollups. The recorded set:

| Fact | Field | Source |
| --- | --- | --- |
| Declared role | `PortfolioMember.role` | manifest only — never inferred |
| Protocol styles | `PortfolioMember.styles` | contract docs observed |
| API documents / operations / gateway routes / external APIs | `apis`, `operations`, `gateways`, `external_apis` | counted, not estimated |
| Owner | `owner` | `None` when unresolvable |
| Remaining deprecated-API callers | `DeprecationReadiness.remaining_clients` | `None` ("no client repos") ≠ `0` ("no call sites") |
| Observed traffic / contract age / sunset | `observed_traffic`, `contract_age_days`, `sunset_date` | evidence or `None` |
| Quality dimensions | `QualityDimension.value` | text like "2/3 operations have operationId", or "unknown" |
| Health | `FleetHealth` counts | five separate counts — never one number |

Absence is always explicit: missing member repos land in
`members_missing`, missing signals produce `UnknownFact`s on the
question or field. A portfolio answer that cannot be measured is
`unknown`, not zero.
