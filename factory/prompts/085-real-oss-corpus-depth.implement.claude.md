You are implementing Loop Factory spec `085-real-oss-corpus-depth`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\085-real-oss-corpus-depth.md`
        Spec hash: `6880e6ce3cf27d9e05bc09516f4db6c20d31e6f410b34fed40efe8b8c1e939ea`

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
- `forge-doctor-api lab`

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions from `prompt_evo_rc_hardening.md`
  Phase 5 and items §8/§16.
- Problem: the corpus holds 18 real slices + 7 negatives. RC claims
  "real-world proven" across frameworks/protocols; the current set
  is OpenAPI-heavy and thin on Spring/Express/NestJS source slices,
  Kong/Envoy configs, K8s Gateway/Ingress, and multi-repo workspace
  scenarios. Precision/recall is reported overall but not broken
  down per framework/protocol/rule-family.
- Out of scope: quantity for its own sake (prompt: ">= 30 only if
  quality holds"); upstream tests; dynamic/API-server corpora;
  vendor-proprietary formats without a license to vendor.
- Review failure: slices that are hand-written paraphrases with
  invented provenance; ground truth that copies analyzer output
  instead of documenting expected entities; negatives that are
  malformed files rather than adversarial-but-parseable.
- Riskiest assumption: enough permissively-licensed real sources
  exist to reach 30 — RESOLVED: count includes existing 18; new
  slices come from established permissive projects (AsyncAPI
  examples, googleapis protos, OAI learn, spring-petclinic,
  nestjs sample, envoy/k8s docs) — see provenance per file.
- Smallest acceptable: corpus reaches >=30 real provenance-carrying
  slices total; every domain in the matrix has >=1 positive + >=1
  negative/adversarial case; manifest gains ground-truth fields;
  lab report prints per-domain + per-rule-family precision/recall.

# Context

Phase 5. Existing: `tests/fixtures/oss/` manifest+sha256+findings,
`tests/fixtures/oss-negative/` status classes, `labs/realworld/`
15 scenario dirs, `labs/oss/` slice corpus, `docs/corpus.md`,
`test_oss_corpus.py` verifying sha256 + expectations. Missing:
framework-source slices (routes from real Express/NestJS/Spring
code), gateway/ingress slices (Kong/Envoy/K8s Gateway), external-API
dependency fixtures, ground-truth schema, per-domain metrics.

# Acceptance Criteria

- OSS corpus grows to >=30 provenance-carrying slices total
  (existing 18 + >=12 new). New slices cover the domain matrix:
  Spring Boot routes/config, Express routes, NestJS routes,
  GraphQL server schema, gRPC service protos, AsyncAPI/event API,
  Kong declarative config, Envoy config, K8s Gateway API/Ingress.
- Each new slice carries full provenance (source, upstream_url,
  upstream_ref, license, sha256, extraction_note) in the manifest —
  no provenance, no slice.
- Each covered domain has at least one negative/adversarial case in
  `oss-negative/` or a negative ground-truth entry: ambiguous-but-
  parseable inputs, partial configs, dynamic dispatch — cases that
  must produce UNKNOWN or no-finding, not fabricated claims.
- Manifest gains per-slice ground truth: `expected_entities`
  (kinds/domains the slice must yield), `expected_findings`,
  `forbidden_findings` (checks that must NOT fire — precision
  guard), `expected_unknowns` where applicable, `protocol` field.
- `test_oss_corpus.py` extended: forbidden_findings asserted absent;
  expected_entities asserted present; sha256 still pinned.
- `lab` report gains per-domain breakdown: precision/recall grouped
  by slice domain and by rule family (OAS/APISEC/RELAPI/GRPC/GQL/
  ASYNC/...), printed in `--json` and console summary;
  `docs/corpus.md` updated with the matrix.
- Multi-repo workspace scenario: at least one `labs/` scenario with
  separate service + client + gateway trees proving cross-repo
  entity linking or its honest unknown.
- pytest/ruff/lab pass.

# Constraints

- Real provenance only: vendored verbatim or surgically excerpted
  with `extraction_note`; no synthetic files dressed as real.
- Permissive licenses only (MIT/Apache-2.0/BSD/CC0/CC-BY).
- Slices stay small (single file per slice; excerpt large upstream
  files rather than vendoring megabytes).
- All corpus tests offline — fixtures are committed files.
