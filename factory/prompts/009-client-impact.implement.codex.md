You are implementing Loop Factory spec `009-client-impact`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\009-client-impact.md`
        Spec hash: `b78219d8a97667eef02e555c718b043d3b2d207b5a3bda7e4ab242da7f2101c1`

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

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions sourced from §17, §68, §183, §226.
- Problem: a breaking change only matters if someone consumes it — link contract changes to known clients (§225 Phase I).
- Out of scope: GraphQL query parsing (§184 → spec 012), proto stub analysis (§185 → spec 013), cross-repo workspace linking (024) — single-repo client discovery first.
- Review failure: client attributed on weak markers, confirmed-impact claimed without actual usage evidence, missing CLIENT### ids.
- Riskiest assumption: mapping call sites → contract operations is accurate for URL-template literals — mitigate by recording UNKNOWN for dynamic/unresolvable calls.
- Smallest acceptable: detect Python `requests`/`httpx` and JS `fetch`/`axios` call sites in-repo, map to operations, produce impact chain for breaking changes.

# Context

Phase I (§225). `ApiClientModel` (§17) discovers clients from SDKs/HTTP clients; first-pass sources: `requests`, `httpx`, `fetch`, `axios` (§17 list is aspirational — scope per smallest-acceptable). Impact chain: breaking contract change → affected operations → known clients → services/repos (§17, §68 blast radius). Known client usage overrides theoretical risk (§183): removed response field + client uses field = confirmed client impact; otherwise POTENTIALLY_BREAKING.

# Acceptance Criteria

- Client usage extraction: `requests.*`/`httpx.*` calls in Python, `fetch()`/`axios.*` in JS/TS — method + URL literal + (where statically resolvable) response field accesses.
- Call sites map to contract operations via method + normalized path (§181 identity rules); unresolvable/dynamic calls recorded as UNKNOWN, not guessed.
- `ApiClientModel`: client identity, call sites, operations consumed, response fields used, source_location.
- Impact analysis consumes spec 008 output: each breaking change → affected operations → consuming call sites → `CLIENT###` findings distinguishing `confirmed client impact` (§183 — client actually uses the removed/changed element) from `potentially breaking`.
- Blast radius output per §68: changed operation → clients → services (basic, single-repo).
- Graph materialization: Client entities + CONSUMES/CALLS edges.
- Tests per §202 incl. dynamic URLs, interpolated paths, renamed imports (`import requests as r`), adversarial comment/string cases.
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- "Basic" scope per v0.1 (§219) — no SDK-generation analysis, no multi-repo joins.
- Confirmed impact requires actual usage evidence in parsed code — never upgrade on path-shape alone (§183).
- Static analysis only; no execution of scanned code (§1).

# Review Notes

- Verify the confirmed-vs-potential distinction is driven by field-level usage, not just endpoint usage.
- Check JS/TS extraction handles `axios.get(url)` and `fetch(url, {method})` equivalently.
- Confirm demo §226's "known client: frontend-service, blast radius 1" is reproducible with a fixture client repo/dir.
