# Testing

How the suite is layered, which layer owns which risk, and how to
run each. Total: ~1762 tests (`python -m pytest -q`).

## The pyramid

| Layer | Files | Count | Owns the risk that |
| --- | --- | --- | --- |
| **Unit** | `tests/test_*.py` (majority) | ~1200 | a model field, check rule, extractor, or adapter silently misbehaves |
| **Adversarial** | `test_compat_adversarial.py`, `test_sec_rel_adversarial.py` | 74 | a boundary case is over-classified — fabricated breaks, invented budgets, phantom auth chains |
| **Conformance** | `test_contract_conformance.py`, `tests/contracts_cross_doctor/` | 89+ | the `forge-contracts/1` wire payload drifts from canonical fixtures or emits unregistered `x-forge-api` keys |
| **Boundary** | `test_boundary.py`, `test_plugin_boundary.py`, `test_mcp_boundary.py` | 61 | `src/` gains a network/subprocess import, plugin code escapes the trust gate, MCP wire behavior destabilizes |
| **Corpus** | `test_oss_corpus.py`, `forge-doctor-api lab` | 123 + 54 scenarios | real-world input regresses — the 31 pinned OSS slices and 14 negatives are ground truth, not synthetic confidence |
| **Scale** | `test_scale_proof.py`, `test_runtime_stream.py`, `factory/benchmarks/scale_benchmark.py` | 18 + recorded run | memory/window bounds, tombstone semantics, or snapshot round-trips break under the 10k/100k envelope |
| **Smoke** | `factory/release_smoke.py`, `factory/mcp_smoke.py`, `test_packaging.py` | per-run | the built wheel doesn't install, boot, scan, or handshake MCP in a clean venv |

## Why this shape

- **Unit tests are cheap and dense** — they pin semantics one field
  at a time (`Confidence.UNKNOWN` requires `unknowns`, sorted
  emissions, entity-id shape).
- **Adversarial tests pin the honest-answer boundary** — the most
  valuable kind of test for a doctor tool is the one that proves it
  says *unknown* rather than inventing a policy from a YAML
  `examples:` block or a verb convention.
- **Conformance + boundary tests protect the wire** — consumers of
  `forge-contracts/1` and MCP must never see silent drift; these
  layers fail on it mechanically.
- **Corpus + scale prove it in the real world** — pinned upstream
  sources and measured envelopes replace claimed coverage.
- **Smoke is the last gate** — everything above runs against the
  source tree; smoke runs against the artifact that actually ships.

## Invariants every layer enforces

- Determinism: no wall-clock, no LLM calls, sorted collections.
- Evidence-first: a finding without evidence or an unknown without
  `UnknownFact` fails at the model layer.
- Sockets are hard-blocked in tests (`conftest.py`) — offline-first
  is enforced, not assumed.
