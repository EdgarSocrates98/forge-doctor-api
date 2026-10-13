You are implementing Loop Factory spec `077-real-oss-corpus`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\077-real-oss-corpus.md`
        Spec hash: `17f042f90196b00847cfd5f7018b3e0e19a2927251e7d6679481ca85b601ac23`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Claude Code subagents or dynamic workflows only when task is parallel. Prefer project skills in .claude/skills when relevant.

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

- Owner: project owner; decisions from stabilization prompt Phase G.
- Problem: every lab fixture is synthetic — hand-written to match the
  analyzers. Precision/recall numbers prove the analyzer agrees with
  itself, not that it reads real-world specs.
- Out of scope: fetching corpora at test time (offline-first is a hard
  rule — corpus slices are vendored, never downloaded); full upstream
  spec files where a focused excerpt proves the point.
- Review failure: vendored slices with no provenance (unverifiable,
  possibly fabricated); slices edited to make tests pass
  (provenance hash prevents this); negative cases that are just
  "empty file" instead of real malformed real-world input.
- Riskiest assumption: upstream licenses allow vendoring excerpts —
  RESOLVED: only permissive-license sources (Apache-2.0/MIT/BSD),
  each slice carries `PROVENANCE.yaml` with upstream URL, commit/tag,
  license, sha256 of the verbatim slice; slices are verbatim excerpts
  (no normalization), asserted by hash.
- Smallest acceptable: ≥12 vendored real-world slices across OpenAPI
  3.x, AsyncAPI, GraphQL SDL, protobuf (Stripe-style naming covered),
  each with provenance + expected findings; ≥6 negative cases
  (malformed YAML, truncated protobuf, invalid GraphQL SDL, wrong
  dialect OpenAPI); corpus manifest asserting hash-verbatim.

# Context

Phase G. `tests/fixtures/` and `labs/` corpora are synthetic.
Candidate sources (all permissively licensed, verified via web
research): kubernetes/api OpenAPI, github/rest-api-description,
stripe/openapi, OAI/OpenAPI-Specification examples, asyncapi/spec
examples, googleapis/googleapis protos, graphql-spec SDL examples.

# Acceptance Criteria

- `tests/fixtures/oss/<source>/<name>/` directories; each contains the
  verbatim slice + `PROVENANCE.yaml`
  `{source_url, upstream_ref, license, sha256, extracted_at_note}`.
- `tests/test_oss_corpus.py`: (a) every PROVENANCE sha256 matches the
  slice bytes (tamper-proof), (b) each slice parses and produces its
  declared expected findings via the real analyzer pipeline,
  (c) every slice's license is in the allowlist, (d) slices sorted in
  manifest — deterministic enumeration.
- ≥6 negative cases under `tests/fixtures/oss-negative/` each
  asserting a specific failure mode (parse error / UNKNOWN finding /
  explicit unsupported), never a crash and never a guessed finding.
- Lab runner can include `oss/` scenarios; run record lists the
  corpus origin per scenario.
- `docs/corpus.md` documents provenance policy + how to add a slice.
- pytest/ruff/mypy pass; suite remains fully offline.

# Constraints

- Verbatim slices only — a hash mismatch means the slice was edited
  to pass, which is exactly the failure mode this spec exists to
  prevent.
- Total vendored size stays modest (< ~2MB) — slices, not dumps.
