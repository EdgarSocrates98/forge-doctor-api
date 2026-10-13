---
id: 062-reliability-depth
title: Reliability depth — retry amplification + timeout-cascade candidates
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §79-§81.
- Problem: reliability checks cover missing timeouts/retries per
  client; §79-81 ask for composed risks — retry amplification across
  hops, timeout-vs-dependency mismatch cascades.
- Out of scope: simulation, load modeling; runtime-metric-based
  probabilities (static evidence only).
- Review failure: amplification findings from same-name services in
  different files; a cascade finding when timeouts are actually
  ordered sanely; verdict-grade language on candidate evidence.
- Riskiest assumption: amplification evidence — RESOLVED: a chain
  edge exists only when both hops are declared (client config +
  callee route/service evidence); amplification = retry count
  multiplication across *evidenced* chain length; unknown chain
  length → bounded range + UnknownFact.
- Smallest acceptable: retry-amplification candidate check +
  timeout-cascade candidate check + composed-chain fixtures +
  confidence/unknown calibration tests.

# Context

§79-§81: retry amplification and timeout cascades as composed
reliability risks. Evidence-only chains; candidates, not verdicts.

# Acceptance Criteria

- `checks/reliability.py`: `APIREL0xx` retry-amplification —
  client retry>1 on a path that reaches another service which itself
  retries → CANDIDATE finding with the evidenced chain + computed
  amplification bound.
- `APIREL0xx` timeout-cascade — caller timeout < callee timeout (or
  callee unknown-timeout) on an evidenced chain → CANDIDATE; exact
  numbers in evidence.
- Chain edges only from declared config/runtime evidence; name
  similarity never creates a hop.
- Tests: evidenced chain → finding, name-only → none, unknown-timeout
  → UNKNOWN+UnknownFact, determinism.
- pytest/ruff/mypy pass.

# Constraints

- Candidate grade; evidence lists every hop or states the unknown.
