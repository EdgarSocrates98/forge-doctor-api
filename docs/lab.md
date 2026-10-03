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
pass/fail and per-family precision/recall.

## Determinism harness

The runner injects a fixed `today` per scenario (temporal checks like
deprecation windows stay reproducible), runs detection-gated pipelines
(graphql scenarios only run when graphql files exist), and compares
finding ids, entities, edges, and unknowns — not prose.
