# Cache intelligence

`load_cache_model(context, files, openapi=...)` builds an
`ApiCacheModel` — the *declared* cache surface of an API (§151–§153).
Everything on this page is evidence-first: a field the source did not
declare stays `None`, and a file that cannot be parsed becomes an
`UnknownFact`.

## CachePolicy (§151)

```text
subject        operation identity or config scope (e.g. "GET /pay", "/static")
layer          client | cdn | gateway | service | database | unknown
ttl            declared TTL — None unless the source wrote it
key            declared cache key — None unless declared
invalidation   declared invalidation trigger — None unless declared
stale_policy   declared stale-while-revalidate/stale-if-error — None unless declared
location       SourceLocation evidence for the declaration
```

## Layers (§152)

Extraction is per-source:

| Source | What is extracted | Layer |
|---|---|---|
| OpenAPI response headers | `Cache-Control` declared on a response | `client` (or `cdn` if declared) |
| `cache:` / `caching:` config keys | scope → ttl/key/invalidation/stale_policy | `service` (unless `layer:` overrides) |
| `cdn:` config keys | scope → ttl | `cdn` |
| `ttl:` config keys | scope → ttl | `service` |

Two deliberate gaps, both honest:

- The OpenAPI model retains response header **names**, not values — so
  a declared `Cache-Control` header proves client-layer caching exists,
  but `ttl` stays `None`. Claiming a TTL would be fabrication.
- `database` has no declared evidence source in scope; a layer that is
  only ever inferred would produce false confidence, so nothing
  defaults to it.

## Invalidation risk (§153)

`InvalidationRisk` fires **only** when two evidence sets coexist:

1. a `CachePolicy` covering a subject, and
2. a mutating method (`POST`/`PUT`/`PATCH`/`DELETE`) on the same path
   in the OpenAPI contract.

The result is a `FindingClass.CANDIDATE` at `Confidence.LOW` — a
hypothesis for a human or the agentic Forge to investigate, never a
verdict. A cached path with no writers produces **no** risk entry; a
write-heavy path with no declared policy produces none either. The
engine does not assert invalidation problems it cannot evidence.

## Malformed input

A `*.yaml`/`*.json` file containing `cache:`/`cdn:`/`ttl:` markers that
fails YAML parsing records an `UnknownFact` ("file has cache markers
but invalid YAML") — coverage gaps are data, not silence.

## Determinism

Policies sort by `(subject, layer)`; risks sort by `subject`. Same
inputs → identical `ApiCacheModel`, verified in
`tests/test_cache.py`.

## Cache graph (spec 063)

`analyzers/cache/graph.py` links mutating operations to cached reads —
but only where resolved `$ref` evidence shows both reference the same
declared `#/components/schemas` component. Prefix-only or name-only
similarity never creates an edge.

- `APICACHE001` stale-window candidate: a cached subject with a
  declared TTL and an evidenced writer; the literal window math goes
  into the finding description.
- `APICACHE002` cross-layer conflict candidate: multiple cache layers
  declare conflicting `stale_policy` values for one subject.

Every edge and finding carries evidence; output is sorted.
