# RC discipline

Rules binding the release-candidate window — the period between the
`0.2.0` RC build and the decision to leave RC. These rules are
enforceable: each forbidden class has a gate that turns red, not a
promise. [rc-policy.md](rc-policy.md) defines the stability classes;
this doc binds behavior *during the window*. Release mechanics stay
in [release.md](release.md).

## Allowed during RC

| Change | Condition | Gate |
| --- | --- | --- |
| Bug fixes | root cause + regression test | pytest |
| FP/FN fixes (check precision) | corpus/lab precision may only move up | `forge-doctor-api lab`, corpus tests |
| Compatibility fixes | additive change kinds only | `test_compat*.py` |
| Runtime/scaling fixes | recorded envelope may only improve | `scale_benchmark.py --check` |
| Docs corrections | links/commands/examples stay honest | `test_docs_contract.py` |
| Test additions | always | pytest |
| Additive `x-*` contract extensions | registered + conformance-tested | `test_x_forge_api_registry_matches_emitted_keys` |
| Release fixes | CI/release workflow, artifact scripts | `test_release.py`, `test_rc_pipeline.py` |

## Forbidden during RC

| Change | Gate that catches it |
| --- | --- |
| New framework generation / new adapter | `rc-baseline` surface counts + `test_boundary.py` |
| Protocol redesign / new contract family | `contract_version`/`forge_protocol_version` fields in `rc-baseline.json` |
| Public-surface changes (CLI commands, MCP tools, check-id removals) | `rc_baseline.py --check`, `mcp_inventory.py --check`, docs-contract |
| New plugin trust classes | `plugins/trust.py` boundary tests; AGENTS.md hard rules |
| New runtime dependencies | `sbom.py --check`, `pyproject.toml` review, minimal-install CI leg |
| Breaking CLI changes | `cli/catalog.py` golden help snapshots |
| Version bumps | `AGENTS.md` pin + `version_gate.py` (owner-documented rationale required) |
| Major architectural expansion | out of RC scope by definition — re-spec outside the window |

## Exceptions

An exception requires **owner approval recorded in the PR** and a
`factory/specs/` entry describing the deviation before merge — the
same bar this program applied to its own specs. "The gate would let
it pass" is not approval.

## What ends the window

The RC window closes when the owner decides, after the `1.0`
triggers in [versioning.md](versioning.md) are evaluated:

1. a downstream Data Doctor / Forger release consumes a
   `forge-contracts/1` payload unchanged, and
2. the CLI inventory + check catalog stayed additive-only for the
   full window (proven by `rc-baseline`/`mcp-inventory` drift gates
   going green for the cycle).

Until then: `0.2.x`, additive-only, evidence-first.
