---
id: 023-policy
title: Policy engine — org policies, inheritance, exceptions, ownership
agent: claude
risk: medium
grill: required
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from §105, §106, §107, §186, §187, §188, §189.
- Problem: organizational rules (auth required, SLO required, deprecation limits, owner required) need a declarative engine feeding findings + PR gates.
- Out of scope: policy *distribution* systems, OPA/Rego integration, the PR-gate CI wiring (030).
- Review failure: exceptions honored without expiry/approval, inheritance order wrong, policies firing without declared org config.
- Riskiest assumption: policy file format — OPEN: confirm simple YAML policy documents (repo-owned schema, documented) vs adopting an existing engine; lean YAML per §3 deps discipline.
- Smallest acceptable: policy model + evaluator over existing findings/models + inheritance + exceptions + ownership/tags resolution.

# Context

Policies (§105): e.g. public APIs require auth, critical APIs require SLO, no wildcard CORS, minimum deprecation period, operationId required, owner required. Inheritance (§106): Organization → Domain → Workspace → Repo. `PolicyException` (§107): rule, scope, owner, justification, created, expires, approval. Ownership sources (§186): CODEOWNERS, OpenAPI extensions, catalog metadata, service config, platform contract. Tags/domains explicit (§187). Org policy examples (§188). Doc coverage detection (§189): operation/schema/error/deprecation docs — opportunity not error.

# Acceptance Criteria

- `ApiPolicy`/`PolicyRule` model: condition (entity selectors + predicates over models/findings), severity override, scope.
- Built-in rule templates for §105/§188 examples; org policies loadable from YAML policy files in workspace/repo config.
- Inheritance chain Org→Domain→Workspace→Repo (§106): repo overrides narrow, never silently widens without exception record.
- `PolicyException` (§107) with expiry + approval fields; expired/non-approved exceptions ignored and surfaced as findings.
- `POLICY###` findings namespace (§218); violations emitted with policy provenance (which level, which file).
- Ownership resolution per §186 sources with precedence order recorded; `ApiOwnership` attaches owner/domain tags (§187) to entities.
- Documentation-coverage signals (§189) as opportunity-level findings.
- Tests per §202 incl. conflicting policies across levels and expired exceptions.
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- Policies are declarative data, not code; evaluation is deterministic.
- Missing policy config → no policy findings (don't invent org rules).
- Exception fields are mandatory — no anonymous permanent exceptions.

# Review Notes

- Verify precedence: closest scope wins; confirm the "never widens silently" rule.
- Check owner resolution handles conflicting sources with recorded precedence.
