---
id: 058-lab-realworld
title: Forge Lab 2.0 — real-world corpus, per-family metrics, confidence bounds
agent: claude
risk: high
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §57-§60, §97.
- Problem: lab corpus is authored fixtures (~40 dirs); §57-60 require
  pinned/sanitized real-world cases, 50→100→500 progression, per-rule
  metrics with coverage confidence — never one-sample claims.
- Out of scope: fetching corpora at test time (corpus is committed,
  sanitized, minimal); 100/500 scale (infrastructure supports the
  progression; corpus growth is content work spread over waves).
- Review failure: a "real-world" fixture that is another authored
  sample; metrics that claim precision from a single expected label;
  lab failures silenced by lowering expectations instead of fixing
  the analyzer.
- Riskiest assumption: sourcing — RESOLVED: distilled minimal slices
  of real open-source projects (pinned commit recorded in fixture
  README, attribution kept, payloads scrubbed) — each fixture declares
  its provenance block {source_url, commit, license, excerpt_reason}.
- Smallest acceptable: corpus format + provenance + 15 new real-world-
  derived cases spanning the §59 adversarial classes + lab runner
  emitting per-rule TP/FP/FN/precision/recall/unknown-rate/
  unsupported-rate + coverage-confidence note per rule.

# Context

§57-§60: real-world corpus, 50→100→500, per-rule/family metrics,
coverage confidence, adversarial classes list. §97: never claim
confidence from one expected sample.

# Acceptance Criteria

- Fixture provenance block mandatory for `realworld/` corpus dirs;
  runner validates it.
- ≥15 new realworld cases covering: monorepo, mixed languages,
  generated code, vendored code, ambiguous routes, dynamic
  frameworks, duplicate services, partial config — each with
  expectations.json.
- Lab runner gains per-rule-family metrics (tp/fp/fn, precision,
  recall, unknown_rate, unsupported_rate, parse_failures, time,
  memory, sample_size) + `coverage_confidence` (low/medium by
  sample-size bands, documented heuristic — never a claim).
- `forge-doctor-api lab` prints the metrics table; `--json` export.
- Baseline updated; adversarial corpus still all-pass; pytest/ruff/
  mypy pass.

# Constraints

- Committed sanitized minimal slices only — no network fetch, no
  payloads, attribution required.
- A rule with <N samples reports `coverage_confidence: low` — hard
  rule, not a warning.
