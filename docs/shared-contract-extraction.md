# Shared contract extraction — criteria and current decision

The API Doctor and the Data Doctor share `forge-contracts/1` as a
published wire contract, vendored into each package
(`contracts/models.py`, `contracts/schemas.py`) rather than imported
from a common dependency. This doc records when a field or shape
qualifies to move into the shared vocabulary — and why no shared
package is extracted yet.

## Extraction criteria

A field graduates to the universal contract only when **all** hold:

1. **Same semantics in both doctors** — the value means the same
   thing for an API finding and a data finding (e.g. `severity`,
   `confidence`, `subject/reason` on unknowns). A field that means
   "route path" here and "table name" there is domain data, not
   universal — it stays under `x-forge-*`.
2. **Same lifecycle** — produced, bounded, and truncated the same
   way. If one doctor synthesizes a field lazily and the other
   eagerly, it is not yet universal.
3. **Same null semantics** — required-scalar missing/null is an
   error; collections decode missing/null/`[]` to empty; optional
   scalars decode to absent. A field whose "absent" means something
   different per doctor stays an extension.
4. **Same version negotiation** — the field participates in
   `<family>/<major>` negotiation identically; additive in the same
   major, removal requires a new major.
5. **Same forward compatibility** — unknown `x-*` keys survive
   round trips in both decoders; strict surfaces reject unknown
   non-`x-*` keys the same way.

## Current decision: keep vendoring

`forge-contracts/1` stays a *vendored contract* — each doctor ships
its own decoder emitting identical bytes, proven by the canonical
fixture pack (`tests/fixtures/contracts/canonical/`) plus the
cross-doctor fixture vendored verbatim from the Data Doctor's
published output. A shared Python package is deferred because:

- the contract is small enough to vendor faithfully (10 schemas);
- extraction couples release trains — a contract bump would force
  synchronized releases of both doctors;
- wire conformance is proven by fixtures, which are
  language-neutral — a non-Python consumer can implement against
  the same `schemas` + fixtures without importing either package.

Revisit when: a third doctor needs the contract AND the fixture
suite shows drift costs exceeding a synchronized release, or either
doctor needs a `forge-contracts/2` major — the extraction criteria
above become the migration spec.

## What stays doctor-specific

Anything listed in [x-forge-api.md](x-forge-api.md): entity ids,
evidence refs, operation ids, runtime signal payloads — observable
API-domain particulars that must never leak into the universal
layer. The conformance suite asserts no non-`x-*` API-specific key
appears at a bundle root.
