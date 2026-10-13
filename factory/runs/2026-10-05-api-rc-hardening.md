# Run record — api-rc-hardening (specs 081–091)

Program: `prompt_evo_rc_hardening.md` phases 1–11, executed on branch
`rc-hardening/081-091`. Base commit `0ca567f` (pre-program HEAD);
specs authored in `b0ddc2f`. Every row's result was produced by the
listed command during the session, not planned.

| Spec | Status | Impl commit | Verification | Result | Known gaps |
| --- | --- | --- | --- | --- | --- |
| W0 spec authoring | done | `b0ddc2f` | `loop-factory grill` per spec | 11 specs grilled+planned | — |
| 081 baseline freeze | accepted | `8402d5f` | `pytest`, `rc_baseline.py --check` | baseline pinned 28 CLI / 17 MCP / surfaces | baseline records file count, not test count |
| 082 cross-doctor conformance | accepted | `9f4169a` | `pytest tests/test_contract_conformance.py` | canonical fixtures + x-forge-api registry gate | Data Doctor fixture is simulated (no upstream artifact yet) |
| 083 MCP boundary | accepted | `2c99f3f` | 22 boundary tests + `mcp_smoke.py` | stable errors, frozen inventory, bounded payloads, malformed-stdio resilience | full suite 1556 at close |
| 084 plugin trust | accepted | `f6bb4c4` | 32 boundary tests | AST import gate, result validation, no-network/mutation proofs | AST gate is conservative (dynamic `forge_doctor_api.*` imports allowlisted) |
| 085 OSS corpus depth | accepted | `0b13483` | 123 corpus tests + lab 54/54 | 31 pinned slices / 14 negatives / per-domain P/R / multi-repo workspace | slices are single files — no multi-file real repos; 1666 total at close |
| 086 runtime scale | accepted | `13023d5` | `scale_benchmark.py --check` + recorded tier | 10k/100k envelope; churn + snapshot tiers; cycle-hang + tuple-decode bugs fixed | snapshot load 121.5s for 18.8MB — recorded, not gated |
| 087 contract compat | accepted | `071d240` | 41 adversarial tests | nullable/discriminator, GQL011–013, GRPC008–009, ASYNC009–017 engine, 4 client extractors | Java extractor is regex-based (no AST); gRPC stubs detection is module-name based |
| 088 sec/rel adversarial | accepted | `ffc1401` | 33 adversarial tests + lab 54/54 | middleware authz `via`, gateway prefix/path scopes, unresolved-scheme honesty, non-evidence key guards, cache partitions | walkers still descend into unknown future YAML keys — new non-evidence keys must be added to the skip list |
| 089 RC pipeline | accepted | `7434b2e` | 17 tests + `release_smoke.py` + `self_scan.py --check` | manifest/provenance/version-gate/self-scan/wheel-smoke all green in clean venv | manifest `dirty_tree` records build-time state (volatile by design) |
| 090 pre-RC versioning | accepted | `93252e1` | 137 version/docs tests + 1766 full suite | 0.2.0 bump authorized+recorded; docs-as-contract ×4 new gates; scorecard + pyramid docs | — |
| 091 post-RC discipline | this commit | — | `pytest`, `ruff` | rc-discipline, run record, final report | — |

## Commands that produced the numbers

```text
python -m pytest -q                          # suite totals per wave
python factory/rc_baseline.py --check        # surface freeze
python factory/version_gate.py               # version consistency
python factory/self_scan.py --check          # dogfood shape
python factory/release_smoke.py --extras "[graphql,mcp]"  # wheel proof
forge-doctor-api lab                         # corpus precision/recall
python factory/benchmarks/scale_benchmark.py --check     # scale envelope
```

Program totals: 74 → 81 test files, 1438 → 1766 passing, 16 → 31 OSS
slices, 7 → 14 negatives, 53 → 54 lab scenarios, CLI/MCP/contract/
dependency counts unchanged (frozen surfaces held).
