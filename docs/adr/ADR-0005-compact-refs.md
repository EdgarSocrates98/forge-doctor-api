# ADR-0005 — Compact references over payloads in handoff/context

- Status: accepted
- Date: 2026

## Context

Handoff bundles (`ApiHandoffBundle`) and `doctor://` context slices
feed downstream agents (API Forge, The Forger). Early sketches carried
raw schema bodies, span payloads and config text — unbounded size,
secret leakage through free text, and duplication of data the Doctor
already addresses by content hash.

## Decision

- Handoffs and context slices carry **refs and compact summaries**,
  never payloads: entity ids (`kind:domain:identifier`), `doctor://`
  URIs, content shas, counts and evidence pointers.
- `ForgeRef`/`context_slice` mint deterministic refs; the consumer
  resolves them back through the broker when (and only when) it needs
  the underlying slice.
- Everything emitted is already redacted at model construction —
  but refs are preferred even over redacted payloads: they stay small,
  deduplicated and versionable.
- Bundles embed `DomainSummary` projections and graph edge exports,
  not models.

## Consequences

- Handoff size is bounded by the *shape* of the project (entities,
  findings) not by the *size* of its schemas/traces.
- Secret hygiene is structural: a ref cannot leak a payload it never
  contained.
- Consumers pay one indirection per ref — acceptable because refs are
  deterministic and the broker resolves them offline.
- Snapshots follow the same rule: compact report JSON, no spans, no
  schema bodies.

## Alternatives

- **Full-payload handoff** — rejected: unbounded, leaks secrets,
  duplicates the evidence store.
- **Compressed payload bundles** — rejected: still unbounded and
  still payload; compression is a size hack, not a boundary.
- **On-demand query API instead of refs** — rejected: the Doctor is
  offline-first and importable as a library; refs resolved through the
  broker give the same laziness without a service.
