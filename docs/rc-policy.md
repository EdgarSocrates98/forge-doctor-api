# RC policy — stability classes and change rules

The release-candidate wave freezes the public surface into named
stability classes. Every surface in [public-surface.md](public-surface.md)
carries exactly one class; the class decides what may change without a
major of the relevant versioning axis (package semver, contract family,
protocol version). Companion: [rc-baseline.json](rc-baseline.json)
records the measured surface this policy governs.

## Stability classes

| Class | Meaning | Change rule |
| --- | --- | --- |
| STABLE | Public contract. Behavioral or breaking change requires a MINOR bump + changelog + migration note. Additive change (new optional fields, new flags) is allowed in MINOR. | break ⇒ MINOR + note |
| WIRE | Cross-implementation contract (`forge-contracts/1`, Forge protocol). Changes follow the family's own negotiation: additive fields are compatible, removed/renamed fields bump the major. Never versioned by package semver alone. | additive ⇒ same major; removal ⇒ new major |
| UX | Human-facing presentation: console formatting, progress output, error wording. May change in PATCH as long as `--json`/machine output stays STABLE. | changeable in PATCH |
| EXPERIMENTAL | Shipped for evaluation; may change or disappear in any MINOR. Never relied on by other surfaces; always marked in docs and `--help`. | unconstrained in MINOR |
| INTERNAL | Not public. Anything not listed in `public-surface.md` is INTERNAL by default — module paths, function signatures, internal file formats. | unconstrained |
| DEPRECATED | Still works, scheduled for removal. Emits a deprecation marker; removed only in a MINOR after ≥1 MINOR of deprecation. | removal ⇒ MINOR after notice |

## Rules

- A surface promoted EXPERIMENTAL → STABLE is a deliberate,
  documented act (changelog + this doc + public-surface.md updated).
- Demoting or breaking a STABLE/WIRE surface without the required
  bump and note is a release-blocking defect.
- New public surfaces enter as EXPERIMENTAL unless the change that
  adds them explicitly promotes them (same artifacts updated).
- The `x-*` extension namespace on WIRE payloads is always
  additive-compatible — consumers must ignore unknown `x-*` keys.
- During the RC window, `docs/rc-discipline.md` tightens these
  rules further (fixes only; no surface movement).
