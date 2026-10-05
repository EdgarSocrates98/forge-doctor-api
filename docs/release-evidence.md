# Release evidence — stabilization program

Record of the stabilization program executed on branch
`stabilization/forge-contracts-conformance` (specs 071–080).
Companion to [release.md](release.md) and
[release-policy.md](release-policy.md).

## Scope anchors

- **Initial HEAD:** `16d14a5` (`main` at branch point).
- **Program HEAD:** recorded per wave below; see `git log main..HEAD`.
- **Trigger evidence:** a clean minimal install of the package
  produced `3 failed / 1232 passed / 26 skipped` against
  documentation that claimed full-suite green, 70 shipped specs, and
  a 43/43 lab — the program exists to close claim↔reality drift.

## Verification matrix (final)

| Gate | Command | Result |
| --- | --- | --- |
| Tests | `python -m pytest -q` | **1438 passed** |
| Lint | `python -m ruff check .` | clean |
| Types | `python -m mypy src` | clean (231 files) |
| Build | `python -m build` | wheel + sdist |
| Lab | `forge-doctor-api lab` | all scenarios pass or skip with reason |
| Scale | `factory/benchmarks/scale_benchmark.py --check` | within budget |
| SBOM | `factory/sbom.py --check` | artifact matches pyproject |
| Sums | `factory/sha256sums.py --verify` | manifest matches dist/ |

## Install matrix

| Profile | Python | Result |
| --- | --- | --- |
| minimal (core only) | 3.11 | graphql/mcp scenarios **skip with reason**; zero failures |
| full `[graphql,mcp]` | 3.11 / 3.12 / 3.13 | zero skipped, zero failed; wheel smoke passes |

## Test-count trajectory

| Point | Count |
| --- | --- |
| Clean install before program | 1232 passed, **3 failed**, 26 skipped |
| After specs 071+073 | 1272 passed |
| After spec 074 (wire contract) | 1304 passed |
| After spec 075 (boundary) | 1344 passed |
| After spec 076 (runtime/scale) | 1349 passed |
| After spec 077 (OSS corpus) | 1398 passed |
| After spec 078 (framework depth) | 1415 passed |
| After spec 079 (sec/rel precision) | 1434 passed |
| After spec 080 (release maturity) | **1438 passed** |

## Measured scale envelope (spec 086)

`factory/runs/scale-benchmark.json` (committed baseline, this host —
tracemalloc-instrumented; CI gates at 4.0x wall / 2.5x peak headroom):

| Kind | Scale | Wall (s) | Peak (MB) | Executions | Traces done/incomplete | Evictions | Late | Tombstone overflow |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| endpoints | 5,000 (check) | 14.5 | 53.9 | — | — | — | — | — |
| endpoints | 10,000 (recorded) | 41.6 | 107.6 | — | — | — | — | — |
| spans grouped | 50,000 (check) | 62.8 | 63.9 | 2,000 | 2,000 / 0 | 0 | 0 | 0 |
| spans grouped | 100,000 (recorded) | 132.3 | 128.0 | 4,000 | 4,000 / 0 | 0 | 0 | 0 |
| spans churn | 50,000 (check) | 104.7 | 91.8 | 50,000 | 10,000 / 40,000 | 40,000 | 500 | 30,000 |
| spans churn | 100,000 (recorded) | 193.9 | 184.0 | 100,000 | 10,000 / 90,000 | 90,000 | 500 | 80,000 |

Snapshot suite (10k endpoints + 10k spans, recorded tier only):
scan 681.8s / 388.2MB peak → 18,831,943-byte snapshot file, load
121.5s, self-diff 0.06s with zero regressions and byte-identical
bounded runtime summary. The snapshot leg is deliberately excluded
from `--check` (recorded tier only) — check-tier runtime stays in the
~2–3 minute band on CI.

Correctness under pressure is asserted inside the run: grouped input
never evicts (trace count < `window`); churn input evicts exactly
`count - window` traces, counts `late_spans` against still-tombstoned
ids, and reports `evictions - tombstone_limit` overflow — any
deviation aborts the benchmark before headroom is even consulted.

## Clean-environment proof (spec 080 verification)

A fresh venv + `pip install dist/*.whl` (no extras) on the built
wheel produced `51 passed / 2 skipped-with-reason / 0 failed` on
`forge-doctor-api lab` — the original `3 failed / 26 skipped` mode is
closed. This proof caught a real latent bug: `cli/catalog.py`
imported `click`, which typer 0.27 no longer depends on — an
undeclared-dependency break on minimal installs, fixed by duck-typed
annotations.

## Wave record

| Spec | Commit | Wave |
| --- | --- | --- |
| 071+073 install matrix | `6d14ab5` | minimal/full capability split |
| 072 CLI stability | `0fa1248` | inventory, snapshots, drift tests |
| 074 wire contract | `7b225bd` | `forge-contracts/1` conformance |
| 075 boundary | `0e1653f` | purity AST, slim request, bounded handoff |
| 076 runtime/scale | `82cbf0e` | streaming, temporal, perf gate |
| 077 OSS corpus | `2f68ba5` | real slices + provenance + negatives |
| 078 frameworks | `1671c00` | four-adapter depth + labs |
| 079 sec/rel precision | `23ca1c1` | auth chain, idempotency, cache, joins |
| 080 release maturity | `this commit` | changelog, SBOM check, SHA256SUMS |
| 081–085 rc hardening | `rc-hardening/081-091` | baseline freeze, conformance, MCP/plugin trust, OSS corpus depth |
| 086 runtime scale | `rc-hardening/081-091` | 5k/50k check · 10k/100k recorded, full metrics, snapshot suite |

Acceptance evidence per spec: `factory/reviews/` and archived spec
files under `factory/specs/archive/2026/`.
