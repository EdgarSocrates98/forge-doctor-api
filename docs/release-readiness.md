# Release readiness scorecard

One row per RC claim. Every claim links the artifact that proves it
and the gate that would fail if the claim regressed. A row without
a proof artifact does not ship.

| Claim | Proof artifact | Gate |
| --- | --- | --- |
| Install matrix (minimal 3.11 + full 3.11/3.12/3.13, wheel-install smoke) | `.github/workflows/quality.yml` minimal/full legs | `tests/test_packaging.py`, wheel smoke step |
| Contract conformance (`forge-contracts/1` round-trips, x-forge-api registry) | `tests/fixtures/contracts/canonical/`, `docs/x-forge-api.md` | `tests/test_contract_conformance.py` |
| MCP boundary (stable errors, frozen inventory, bounded payloads, malformed-input resilience) | `factory/artifacts/mcp-inventory.json`, `factory/mcp_smoke.py` | `tests/test_mcp_boundary.py`, `factory/mcp_inventory.py --check` |
| Plugin boundary (AST no-import gate, result validation, no network/mutation) | `src/forge_doctor_api/plugins/trust.py`, `plugins/validation.py` | `tests/test_plugin_boundary.py` |
| Corpus depth (31 pinned OSS slices, 14 negatives, per-domain P/R) | `labs/oss/` `PROVENANCE.yaml` files, `docs/corpus.md` | `tests/test_oss_corpus.py`, `forge-doctor-api lab` |
| Scale envelope (10k endpoints / 100k spans, churn + snapshot tiers) | `docs/runtime-scale.md`, recorded run in `docs/release-evidence.md` | `factory/benchmarks/scale_benchmark.py --check`, `tests/test_scale_proof.py` |
| Compat precision (OpenAPI/GraphQL/gRPC/AsyncAPI breaking-change matrix) | `docs/compatibility.md` | `tests/test_compat_adversarial.py`, `tests/test_compat.py` |
| Security/reliability precision (evidence-only budgets, auth-chain honesty, cache partitions) | `docs/security-reliability.md` | `tests/test_sec_rel_adversarial.py`, `tests/test_sec_rel_precision.py` |
| Release artifacts (manifest, provenance, version gate, self-scan, wheel smoke) | `factory/artifacts/release-manifest.json`, `factory/artifacts/provenance.json`, `dist/SHA256SUMS` | `tests/test_rc_pipeline.py`, `factory/*_gate.py --check`, `factory/release_smoke.py` |
| Boundary purity (no network/subprocess in `src/`, evidence-first findings) | `AGENTS.md` hard rules | `tests/test_boundary.py` |
| Dogfooding (the doctor scans itself; shape is pinned) | `factory/runs/doctor-self-scan.json` | `factory/self_scan.py --check` |
| Surface freeze (CLI/MCP/corpus/test counts pinned) | `docs/rc-baseline.json` | `factory/rc_baseline.py --check`, `tests/test_rc_baseline.py` |

## Reading the card

- **Proof artifact** = the file an auditor opens first. If it does
  not exist or does not contain the claim, the claim is false.
- **Gate** = the command or test that turns red. "Tests pass" is
  not evidence; the linked file is.
- Scores and health metrics are deliberately absent — see
  [workspace-fleet.md](workspace-fleet.md) for the portfolio fact
  set; readiness is proven by artifacts, not invented rollups.
