# Forge Lab

`labs/` is the ground-truth corpus that keeps the engine honest — golden
repositories, adversarial fixtures, and per-scenario expectations the
`lab` runner scores against.

## Corpus layout

```text
labs/<domain>/<scenario>/     one fixture project per directory
    expected.yaml             ground truth: expected findings/entities/
                              edges/unknowns + forbidden_ids/entities
labs/adversarial/             cases designed to fool detection:
                              graphql-looking JSON, malformed OpenAPI,
                              decorator-comment "routes", dynamic routes,
                              proto comments, generated code, …
```

`expected.yaml` asserts both the positive space (`expected_findings`
check ids) and the negative space (`forbidden_ids`, `forbidden_entities`,
`forbidden_edges` — e.g. a comment-looking route must produce *no*
entity). `unexpected` findings count as false positives even when a
scenario expects nothing — the FP contract is always active.

## Running

```bash
forge-doctor-api lab              # whole corpus, console report
forge-doctor-api lab --json       # machine-readable report
forge-doctor-api lab --no-record  # skip factory/runs/ record
```

Each run writes `factory/runs/<timestamp>.lab.json` with per-scenario
pass/fail/skip, per-family precision/recall, and the install profile
(`extras_present`/`extras_absent`) the run executed under.

## Capability matrix (specs 071/073)

Optional extras gate parts of the corpus. A scenario declares
`requires_extras: [<name>]` in `expected.yaml`; the `graphql` *domain*
and an explicit `run: [graphql]` also imply the `graphql` extra. When a
required extra is absent from the install:

- the scenario is **skipped** — `skipped: true` + a `skip_reason`
  naming the missing extras;
- it counts under neither `passed` nor `failed`, and contributes no
  evidence to family metrics either direction;
- console output prints `SKIP <domain>/<name> (missing extras: …)` and
  the summary reports `passed / failed / skipped` separately;
- `lab` still exits 0 — minimal install is a supported profile, not an
  error.

"Full corpus" therefore means the full install profile
(`pip install '.[graphql,mcp]'`): zero skipped scenarios. Under a
minimal install the same corpus proves graceful degradation — every
skipped scenario carries its reason in the run record.

## Determinism harness

The runner injects a fixed `today` per scenario (temporal checks like
deprecation windows stay reproducible), runs detection-gated pipelines
(graphql scenarios only run when graphql files exist), and compares
finding ids, entities, edges, and unknowns — not prose.

## Real-world corpus (spec 058)

`labs/realworld/` holds ≥15 cases modeled on real repository shapes:
monorepo multi-service, mixed languages, generated clients, vendored
code, ambiguous routes, dynamic framework config, duplicate services,
and partial gateway/IaC config. Every realworld scenario **must**
declare a `provenance` block (`source`, `retrieved`) in its
`expected.yaml` — a scenario without one fails with a `problems`
entry, never silently passes.

`labs/oss/` holds scenarios whose fixture is a *verbatim vendored
upstream artifact* (see `docs/corpus.md` for the full corpus). The
provenance bar is stricter: `source`, `upstream_ref`, `license`, and
`sha256` of the vendored bytes are all required, and the scenario
fails as a problem entry if any is missing. Every result — pass,
fail, or skip — echoes its `provenance` into the run record, so a
run JSON proves which upstream artifact each corpus scenario
exercised.

## Metrics (spec 058)

Per scenario the harness records: sample size (files scanned), elapsed
ms, peak bytes, unknown count, parse-failure count, unsupported count.
These are *measurements* — they never feed pass/fail matching.

Per family (`OAS`, `APISEC`, `RELAPI`, …) the report aggregates
TP/FP/FN, precision, recall, unknown rate, unsupported rate, parse
failures, elapsed time, peak memory, sample size, and
`coverage_confidence` — a documented band, never a claim:

- `low`: fewer than 10 expected+observed items exercised the family
- `medium`: 10 or more

There is no `high` — lab coverage is always partial evidence. Console
output prints the full metrics table; `--json` exports the same fields
(`tp`, `fp`, `fn`, `precision`, `recall`, `unknown_rate`,
`unsupported_rate`, `coverage_confidence`, plus raw counters).
