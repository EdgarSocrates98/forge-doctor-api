---
id: 061-security-depth
title: Security depth — passive evidence chain + confidence calibration
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §76-§78.
- Problem: security checks exist (APISEC family) but §76-78 ask for
  deeper passive analysis — auth coverage chains, dataflow-ish
  exposure candidates — all confidence-calibrated.
- Out of scope: active scanning, secret detection by content
  (redaction stays), DAST of any kind.
- Review failure: a "missing auth" finding inferred from absence of
  securityScheme on one op while the parent declares it; a
  sensitivity guess by field name treated as fact; confidence
  inflated beyond the evidence.
- Riskiest assumption: new check scope — RESOLVED: two bounded
  additions — (a) auth-coverage chain check: op-level security
  overrides/inheritance audited end-to-end with UNKNOWN where global
  vs op conflict is ambiguous; (b) sensitive-field *candidates*:
  response schema fields matching a documented sensitive-name list
  AND lacking any declared protection (rate limit/redaction marker)
  → CANDIDATE findings, Confidence.LOW.
- Smallest acceptable: the two checks + adversarial fixtures
  (inherited auth, ambiguous overrides, name-only sensitivity) +
  calibrated confidence assertions in tests.

# Context

§76-§78: passive security depth, confidence calibration. §119
resource-signal rules apply: candidates, never verdicts.

# Acceptance Criteria

- `checks/security.py` additions: `APISEC0xx` auth-coverage-chain —
  audits global↔op security inheritance; ambiguous → UNKNOWN +
  UnknownFact; `APISEC0xx` sensitive-field candidates — schema-field
  name in documented list + no protection evidence → CANDIDATE/LOW.
- Findings carry the full evidence chain (global scheme, op override,
  field location).
- Adversarial fixtures: op inheriting parent auth (no FP), ambiguous
  override (UNKNOWN not PASS/FAIL), name-only field with declared
  redaction (no finding).
- pytest/ruff/mypy pass.

# Constraints

- Evidence chain in every finding; candidates labelled, LOW
  confidence where name-matching is the only signal.
