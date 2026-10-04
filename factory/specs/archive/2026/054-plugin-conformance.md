---
id: 054-plugin-conformance
title: Plugin conformance suite — determinism/offline/evidence verification
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §54-§56.
- Problem: trust says *what* runs; nothing proves an activated plugin
  *behaves* — a plugin could inject nondeterminism, network calls, or
  evidence-free findings and poison the Doctor's guarantees.
- Out of scope: sandboxing/isolation beyond the conformance checks
  (full process isolation is roadmap — record it); performance
  conformance.
- Review failure: conformance that runs the plugin but doesn't assert
  the invariants; a suite a malicious plugin can pass by detecting the
  test; findings validated only by shape not by evidence presence.
- Riskiest assumption: enforceable invariants — RESOLVED: the §55
  checks are structural/behavioral, documented honestly: determinism
  (two runs byte-equal), offline (socket-blocked run), evidence
  compliance (every Finding has ≥1 evidence, every Confidence.UNKNOWN
  has unknowns), no side-effects (fileset diff before/after), output
  compatibility (models serialize through core to_dict).
- Smallest acceptable: `plugins/conformance.py` +
  `forge-doctor-api plugins verify <id>` running the suite + a sample
  violating plugin failing each check in tests.

# Context

§54-§56: conformance for determinism, offline, evidence compliance,
unknown semantics, side-effects, output compatibility. Honest
boundary: conformance detects violations it checks; it is not a
proof — that stays in docs.

# Acceptance Criteria

- `plugins/conformance.py`: `run_conformance(plugin) ->
  ConformanceReport{checks: tuple[CheckResult], passed}` where each
  CheckResult has name/status/details — the six §55 checks.
- Side-effect check: snapshot project fileset (paths+hashes) before/
  after a plugin analysis run → any write = fail.
- Evidence check: every emitted Finding validates via existing
  Finding rules; UNKNOWN-confidence findings carry unknowns.
- Offline check: run under blocked sockets (reuse test_offline
  mechanism in-process via audit hooks where feasible — else document
  the subprocess-CI variant).
- CLI `plugins verify <id>` → report table + exit code.
- Tests: fixture plugin per violation class each fails its check;
  clean fixture plugin passes; determinism.
- pytest/ruff/mypy pass.

# Constraints

- Conformance runs ONLY on already-trusted-and-activated plugins or
  in an explicit `--untrusted-verify` mode that still never imports
  (static checks only for untrusted).
