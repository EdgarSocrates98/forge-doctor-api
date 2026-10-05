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
| 080 release maturity | this commit | changelog, SBOM check, SHA256SUMS |

Acceptance evidence per spec: `factory/reviews/` and archived spec
files under `factory/specs/archive/2026/`.
