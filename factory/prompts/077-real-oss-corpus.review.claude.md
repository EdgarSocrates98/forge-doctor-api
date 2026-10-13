Review Loop Factory spec `077-real-oss-corpus` against current working tree.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\077-real-oss-corpus.md`

        Review stance:
        - Findings first. Focus correctness, regressions, tests, security, maintainability.
        - Compare implementation against acceptance criteria.
        - Run or inspect verification evidence:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`
        - If accepted, say `ACCEPTED`.
        - If not accepted, say `CHANGES_REQUESTED` and list blocking items.
        - Do not move files. Operator or CLI archive step moves accepted specs.

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
