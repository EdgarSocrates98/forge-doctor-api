# Policies, exceptions, and ownership

The policy engine is declarative: YAML policy files declare rules, the
engine evaluates them against loaded models and emits `POLICY###`
findings. No imperative plugin code ever runs.

## Policy files

Any file named `policies.yaml`, `policy.yaml`, or ending in
`.policy.yaml`/`.policy.yml` inside the scanned tree is loaded:

```yaml
level: repo                # organization | domain | workspace | repo
policies:
  - id: repo.require_auth  # stable id; defaults to {level}.{rule}
    rule: require_auth     # one of the built-in rule names
    severity: high         # optional override
    applies_to: "/**"      # optional path-prefix selector
    params: {min_days: 180}  # rule-specific parameters
exceptions: []
```

`scan --policy DIR` merges policies from an additional directory into
the same evaluation — that is how an org-level file can be supplied to a
repo scan.

## Built-in rules

| Rule | Check id | Evaluates |
|---|---|---|
| `require_auth` | POLICY001 | Operations on matching paths carry auth evidence. |
| `require_slo` | POLICY002 | Critical APIs declare an SLO. |
| `no_wildcard_cors` | POLICY003 | No `*` origins on matching operations. |
| `min_deprecation_days` | POLICY004 | Deprecated APIs keep `sunset - announced >= min_days`. |
| `require_operation_id` | POLICY005 | Every operation has an `operationId`. |
| `require_owner` | POLICY006 | Ownership resolves to a team/person. |
| `doc_coverage` | POLICY007 | Operations, schemas, error responses, and deprecations carry docs (§189). |

Engine diagnostics: `POLICY008` ignored invalid exception,
`POLICY009` widened inherited policy, `POLICY010` malformed policy file.
Absent policy files are not an error — evaluation yields zero findings.

## Inheritance and narrowing

Policies resolve per rule across levels `organization → domain →
workspace → repo`. The narrowest level wins **only when it does not
widen** the requirement (stricter severity or stricter params win;
weakening keeps the widest effective policy and emits `POLICY009`) —
unless a valid exception exists.

## Exceptions

```yaml
exceptions:
  - rule: require_auth
    scope: "/internal/**"
    owner: team-a
    justification: "sandbox environment"
    created: "2025-01-01"
    expires: "2027-12-31"
    approval: approved       # pending/expired → ignored + POLICY008
```

All fields are mandatory; a malformed exception entry produces
`POLICY010`, and an expired/unapproved one is ignored with `POLICY008`.
A valid exception suppresses matching violations and permits narrowing.

## Ownership resolution

`resolve_ownership` composes sources in precedence order —
`openapi_extension → catalog → codeowners → service_config →
platform_contract` — recording every source that matched on
`ApiOwnership.sources`. The first hit wins; later hits are still
recorded so conflicts are visible. Missing ownership is data
(`require_owner` violation), never inferred from layout.
