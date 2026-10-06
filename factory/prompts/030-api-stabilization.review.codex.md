Review Loop Factory spec `030-api-stabilization` against current working tree.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\030-api-stabilization.md`

        Review stance:
        - Findings first. Focus correctness, regressions, tests, security, maintainability.
        - Compare implementation against acceptance criteria.
        - Run or inspect verification evidence:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`
- `python -m build --wheel 2>/dev/null || python -m pip wheel . --no-deps -w dist`
        - If accepted, say `ACCEPTED`.
        - If not accepted, say `CHANGES_REQUESTED` and list blocking items.
        - Do not move files. Operator or CLI archive step moves accepted specs.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions sourced from §146–§147, §170–§178, §202–§210, §224.
- Problem: v0.1 must be releasable — deterministic outputs, CI gate, offline proofs, wheel/sdist, quality gate evidence.
- Out of scope: publishing to a registry, signing, hosted dashboards; public-API commitment stays deferred (§210).
- Review failure: network detected in test suite (§204), SARIF invalid, benchmark claims without run records, version bumped past 0.x.
- Riskiest assumption: scope of CI gate — RESOLVED: first gate = `scan` + `contract diff` + configurable `fail-on` (breaking/security/policy) per §177–§178, delivered as a reusable GitHub Action workflow; no other CI systems.
- Smallest acceptable: output writers (console/JSON/JSONL/SARIF/agent-compact), `ApiErrorModel` standard error contract, GH Action scan + PR gate, offline/hermetic test proofs, wheel+sdist, quality-gate run record.

# Context

Stabilization per §170–§180, §202–§210, §224. Outputs (§175): console, JSON, JSONL, SARIF where appropriate (static/contract findings — not forced for runtime summaries, §176), agent compact format. `ApiErrorModel` standard error contract (§146–§147) + org error-policy support. CI (§177): `forge-doctor-api scan` in GitHub Action with `fail-on`, `baseline`, `policy`, `contract diff`; PR gate (§178) configurable: fail on new breaking change / high-confidence security issue / policy violation. Benchmarks (§170): 100/1k/10k endpoints, 10k/100k/1M spans. Memory safety via streaming (§171); compact history storage (§172); no raw trace retention (§173); `schema_version`+`tool_version`+knowledge versions on all exports (§174). Hermetic execution via `ProjectContext` (§203); tests prove offline (§204). Package: wheel + sdist (§205); Python 3.11/3.12/3.13 (§206); Linux/Windows/macOS (§207); dogfood — Doctor scans itself (§208); version 0.1.0 (§209); public API deferred (§210). Quality gate before release (§224): CI green, precision stable, no known P0, golden stable, docs updated, run record.

# Acceptance Criteria

- Output writers per §175: console (Rich), JSON, JSONL, SARIF 2.1.0 for static/contract findings (§176), agent compact format; every export carries §174 metadata.
- `ApiErrorModel` comparison extended to org standard-error-contract evaluation (§147).
- GitHub Action workflow running `forge-doctor-api scan` with `fail-on`, `baseline`, `policy`, `contract diff` inputs (§177); PR-gate exit codes configurable per §178.
- Hermetic proof: test suite runs with network disabled (§203–§204); all host access via `ProjectContext`.
- Streaming ingestion verified at §170 benchmark scales (memory bounded); compact history + no raw trace retention enforced (§172–§173).
- `python -m build`/wheel+sdist succeed (§205); declared support py3.11–3.13 (§206); code is OS-portable — no POSIX/Windows-only paths (§207).
- Dogfood: repo includes a self-scan configuration and a recorded run (§208).
- Quality-gate checklist (§224) template under `factory/` + run record for the v0.1 gate.
- Tests per §202; `python -m pytest -q`, `ruff`, `mypy` pass.

# Constraints

- No registry publish, no 1.0 versioning (§209–§210).
- SARIF only where findings are location-anchored; don't force runtime summaries into SARIF (§176).
- Benchmark claims require captured run records — no unverified numbers.
- Offline guarantee is tested, not asserted (§204).

# Review Notes

- Verify SARIF validates against the 2.1.0 schema.
- Confirm the offline test actually blocks sockets, not just avoids known calls.
- Check `fail-on` semantics: default config, per-category thresholds, and that UNKNOWNs never block a gate unless configured.
