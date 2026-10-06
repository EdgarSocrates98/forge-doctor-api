# Real-world OSS corpus

`tests/fixtures/oss/` holds **verbatim excerpts** of real upstream API
artifacts — OpenAPI 3.x documents, AsyncAPI 3.x documents, GraphQL SDL,
protobuf IDL, framework route sources (Spring, Express, NestJS), and
gateway/mesh declarations (Kong decK, Envoy, Istio, Kubernetes Gateway
API and Ingress) — vendored from permissively-licensed public
repositories at pinned upstream refs. `tests/fixtures/oss-negative/`
holds real malformed/unsupported input and authored adversarial cases
(partial config, dynamic dispatch, ambiguous-but-parseable input)
exercising the analyzers' failure modes.

The corpus exists to answer a skepticism the synthetic lab corpus
cannot: *the analyzers agree with themselves on fixtures written to
match them — do they read real-world specs?* Every slice proves its
bytes and its provenance; every expectation was captured from real
analyzer output, never invented.

## Provenance policy

Each slice directory contains the verbatim artifact (`slice.yaml`,
`slice.proto`, `slice.graphql`, or `slice.json`) plus a
`PROVENANCE.yaml`:

| key | meaning |
| --- | --- |
| `source_repo` | upstream repository URL |
| `upstream_path` | path of the file inside that repository |
| `upstream_ref` | pinned commit sha the bytes were fetched at |
| `license` | SPDX tag of the upstream license |
| `sha256` | sha256 of the vendored file's bytes |
| `extracted_at_note` | how the slice was extracted |

Licenses are restricted to permissive terms —
`Apache-2.0`, `MIT`, `BSD-2-Clause`, `BSD-3-Clause`, `CC0-1.0`,
`CC-BY-4.0` — enforced by `tests/test_oss_corpus.py`. Attribution is
carried by the provenance fields themselves; no upstream text is
relicensed.

A sha256 mismatch between manifest, provenance file, and slice bytes
fails the suite — that hash is the tamper-evidence. Editing a slice to
make a test pass is exactly the fabrication mode this corpus rules
out.

## Layout

```
tests/fixtures/oss/
  manifest.yaml                 sorted slice table (see below)
  <source>/<name>/
    slice.<ext>                 verbatim upstream excerpt
    PROVENANCE.yaml             provenance record
tests/fixtures/oss-negative/
  manifest.yaml                 sorted negative-case table
  <name>/
    slice.<ext>
    PROVENANCE.yaml
```

`manifest.yaml` lists each slice with `name`, `file`, `domain`,
`protocol`, `expected_findings`, `expected_entities`,
`forbidden_findings`, `expected_unknowns` (where applicable) and
`sha256`. Entries are sorted by `name`; the tests assert both the sort
order and that the manifest enumerates exactly the slices on disk.

* `expected_findings` — exact check-id set the pipeline must emit
  (asserted both directions: nothing missing, nothing extra).
* `expected_entities` — report-level entity ids (route ids, operation
  ids, contract/mesh/gateway subjects) that must be present.
* `forbidden_findings` — ids or `PREFIX*` family globs that must *not*
  fire; binds as hard as expected findings. Cross-domain isolation is
  the point: an Express source file must never emit an `OAS*`.
* `expected_unknowns` — unknown subjects that must be recorded when
  the engine cannot evidence something (e.g. a gateway backendRef with
  no manifest target, or a `PROVENANCE.yaml` that a dialect sniffer
  mistook for config).
* `protocol` — `http`, `grpc`, `graphql`, or `events`.

Negative cases record `expect_status` (the document-level parse
status — `MALFORMED`, `UNSUPPORTED_VERSION`, …, or `SCANNED` for
non-document domains where the whole pipeline must simply complete
without raising) plus `expected_findings`, `forbidden_findings`, and
`expected_unknowns`. They assert a specific failure mode, never a
crash and never a guessed finding. Negative `PROVENANCE.yaml` files
carry an `origin` field naming the positive slice or upstream file
they were *derived* from — or the upstream they imitate when authored —
plus `domain`, `sha256`, and `extracted_at_note` describing the
derivation.

## Domain matrix

Every domain in the matrix has **at least one positive slice and at
least one negative/adversarial case**; `test_oss_corpus.py` asserts the
matrix stays covered:

| domain | positive slices | negative cases |
| --- | --- | --- |
| `openapi` | apisguru/worldtimeapi, oai-learn/* (8), swagger-api/petstore | truncated/malformed JSON, truncated doc, swagger-2.0 |
| `asyncapi` | asyncapi/* (4) | unsupported version |
| `grpc` | googleapis/* (3), grpc/routeguide | truncated proto |
| `graphql` | spacexland/schema, swapi-graphql/schema | federation SDL, openapi-as-graphql |
| `spring` | spring-petclinic owner/vet controllers, mvc-core-config | dynamic/placeholder mapping paths |
| `express` | expressjs/route-separation-index | dynamic verb dispatch, concatenated paths |
| `nestjs` | nestjs/cats-controller | env-bound `@Controller` prefix |
| `kong` | kong/deck-gateway-input | services with no routes (partial config) |
| `envoy` | envoyproxy/front-proxy-service | listener without filter_chains |
| `k8s-gateway` | gateway-api/basic-http | HTTPRoute with no parentRefs/rules |
| `k8s-ingress` | kubernetes/ingress-wildcard | Ingress with empty spec |
| `mesh` | istio/bookinfo-virtual-services | — (auxiliary domain) |

Optional-capability slices (e.g. `domain: graphql`) skip with an
explicit reason when the corresponding extra is absent — capability
gaps are recorded, never silent.

## Adding a slice

1. Pick a permissively-licensed upstream file; record its repository,
   path, and the pinned commit sha (`git rev-parse HEAD` or a tag's
   commit — never a floating branch name).
2. Copy the *focused excerpt* into
   `tests/fixtures/oss/<source>/<name>/slice.<ext>` — verbatim, no
   normalization. Keep it small; slices prove coverage, not size.
3. Write `PROVENANCE.yaml` with all six keys; compute
   `sha256` over the slice bytes.
4. Add the manifest entry in sorted `name` order, with
   `expected_findings` taken from an actual `scan_project` run — run
   the analyzer, read its output, record it. Never write expectations
   first.
5. For negative material, place the case under
   `tests/fixtures/oss-negative/` with `expect_status` read from the
   parser's document status vocabulary.
6. `python -m pytest -q tests/test_oss_corpus.py` must pass.

## Lab integration

A corpus slice can also run as a lab scenario under `labs/oss/`:
copy the slice bytes into the scenario directory and declare a
`provenance` block (`source`, `upstream_ref`, `license`, `sha256`) in
`expected.yaml`. The loader fails scenarios missing any required key,
and every lab result echoes its provenance into the run record —
see `docs/lab.md`.

## Sources

| upstream | license | slices |
| --- | --- | --- |
| `OAI/learn.openapis.org` | CC-BY-4.0 | OpenAPI 3.x examples (petstore, uspto, callbacks, links, webhooks, …) |
| `swagger-api/swagger-petstore` | Apache-2.0 | OpenAPI petstore |
| `APIs-guru/openapi-directory` | CC0-1.0 | worldtimeapi.org OpenAPI 3.0 document |
| `asyncapi/spec` | Apache-2.0 | AsyncAPI 3.1 examples (slack-rtm, streetlights, mercure, gitter, …) |
| `googleapis/googleapis` | Apache-2.0 | `google/api` annotations, http, code protos |
| `grpc/grpc` | Apache-2.0 | route_guide example proto |
| `graphql/swapi-graphql` | MIT | Star Wars schema SDL |
| `apollographql/supergraph-demo` | MIT | federation SDL (negative: unsupported directives) |
| `SpaceXLand/api` | MIT | real GraphQL SDL schema |
| `spring-petclinic/spring-framework-petclinic` | Apache-2.0 | `@Controller` sources + Spring XML config |
| `expressjs/express` | MIT | `route-separation` example app |
| `nestjs/nest` | MIT | `01-cats-app` `@Controller` sample |
| `Kong/deck` | Apache-2.0 | declarative Kong state (`_format_version`) |
| `envoyproxy/examples` | Apache-2.0 | front-proxy Envoy config |
| `kubernetes-sigs/gateway-api` | Apache-2.0 | GatewayClass/Gateway/HTTPRoute example |
| `kubernetes/website` | CC-BY-4.0 | wildcard Ingress manifest |
| `istio/istio` | Apache-2.0 | bookinfo VirtualService sample |

Pinned refs live in each `PROVENANCE.yaml`; re-fetching at a *newer*
ref requires regenerating the manifest and re-running the analyzer to
re-capture expectations.
