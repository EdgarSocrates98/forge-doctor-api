You are implementing Loop Factory spec `016-performance`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\016-performance.md`
        Spec hash: `62f44f83b9a81cd5e095dd1df48cf002bb701b64ae29737b9dcb0391cabda157`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Codex subagents when work splits cleanly. Ask explicitly before spawning. Keep final answer terse with files changed and checks run.

        Required verification:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`
- `python -m forge_doctor_api runtime regressions --help`

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions sourced from §33–§38, §88–§97, §148–§150, §154–§155, §168–§169.
- Problem: answer "which runtime paths are slow / regressing / amplifying" — second demo target depends on it (§227).
- Out of scope: SLO/error-budget math (017), incident narratives (021), billing computation (§93 explicitly not a billing calculator).
- Review failure: magic scores, regressions asserted on thin samples, correlation presented as proven causality (§227).
- Riskiest assumption: how much of the experiment engine lands in first pass — RESOLVED: baselines + all §37 regression families + fanout/payload/capacity signals + `Experiment`/`RequestScenario` verdict engine, exercised only on synthetic/lab data (no live request execution in the Doctor).
- Smallest acceptable: `RequestBaseline`, APIPERF001–008, critical-path decomposition, capacity signals, experiment verdict skeleton.

# Context

`ApiPerformanceSignal` families (§33): LATENCY_REGRESSION, DOWNSTREAM_LATENCY, QUEUEING, RETRY_AMPLIFICATION, PAYLOAD_AMPLIFICATION, SERIALIZATION_OVERHEAD, CACHE_MISS_PRESSURE, CONCURRENCY_PRESSURE, TIMEOUT_PRESSURE, FANOUT_AMPLIFICATION, N_PLUS_ONE. `RequestBaseline` metrics (§36/§88): p50/p90/p95/p99, error rate, throughput, retry rate, timeout rate, payload size — per service/operation/route/client/dependency. Robust statistics (§89): median, MAD, p95, p99. Latency decomposition + `RequestCriticalPath` (§34–§35). Change→runtime correlation (§38/§90). `ApiCapacitySignal` (§91) + saturation states HEALTHY/ELEVATED/SATURATED/UNKNOWN with threshold provenance (§92). Cost drivers not billing (§93). Optimization/multi-objective + `Experiment`/`RequestScenario` (§94–§97, §168–§169). Payload model (§148–§150) and latency budget (§154)/SLO critical path (§155) hook in here.

# Acceptance Criteria

- `RequestBaseline` per §36/§88 dimensions; robust stats (median, MAD, p95, p99) with minimum-sample honesty — insufficient data → UNKNOWN.
- APIPERF001–008 per §37: p95 latency regression; error-rate regression; downstream regression; retry amplification; timeout increase; payload growth; fan-out increase; cache-effectiveness regression — each with evidence_kind RUNTIME/DERIVED and threshold provenance.
- `RequestCriticalPath` decomposition per §34–§35: total time broken into auth/service/downstream/serialization when spans allow; incomplete trees → UNKNOWN segments.
- Change→runtime correlation (§38/§90): correlate spec 020 change events with regressions — output states correlation, never asserts causality (§227).
- `ApiCapacitySignal` dimensions (§91) + saturation classification with threshold provenance (§92); `ApiCostDriver` signals (§93).
- `PayloadShape` (§148) + large-payload signal as static candidate + runtime confirmation (§149); serialization signal when exports allow (§150).
- `ApiLatencyBudget` (§154) + SLO-critical-path linkage (§155).
- `Experiment`/`RequestScenario` (§96–§97) with verdicts SUPPORTED/NOT_SUPPORTED/INCONCLUSIVE/CONSTRAINT_VIOLATED (§169) on synthetic scenarios — never live requests.
- CLI `runtime requests|baseline|regressions` per §162.
- Demo §227 reproducible: checkout p95 regression → downstream payments latency regression, no unsupported causality claim.
- Tests per §202 + benchmark smoke per §170 scale.
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- Regression = statistically-backed (median/MAD/percentiles), with sample-size honesty; no magic composite scores (§24 analog, §190).
- Correlation ≠ causality — wording matters (§227).
- Optimization suggestions carry tradeoffs (§95) — latency↓ vs staleness↑ etc.

# Review Notes

- Verify MAD-based regression doesn't fire on single-spike windows.
- Confirm downstream attribution uses parent/child spans, not service-name heuristics.
- Check experiment verdicts list violated constraints explicitly.
