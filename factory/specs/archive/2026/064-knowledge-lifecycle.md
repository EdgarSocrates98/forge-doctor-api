---
id: 064-knowledge-lifecycle
title: Knowledge pack lifecycle — validation, versioning, update path
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §85-§87.
- Problem: knowledge packs load + expose versions, but there is no
  pack validation contract, no update path, no compat check between
  pack version and engine version.
- Out of scope: remote pack distribution (packs are local files);
  pack authoring tooling beyond validation.
- Review failure: a malformed pack partially loading; version compat
  checked by string equality (semver-ish ranges needed); a pack
  silently shadowing a builtin.
- Riskiest assumption: compat semantics — RESOLVED: pack declares
  `doctor_compat: ">=0.1,<0.2"` range; registry validates pack schema
  + compat + id-uniqueness; builtin packs pinned to the engine
  version.
- Smallest acceptable: `PackManifest` validation + compat check +
  `knowledge validate <dir>` CLI + precedence rules documented +
  tests.

# Context

§85-§87: knowledge lifecycle — validation, versioning, update path.
Builds on spec-029 knowledge loader.

# Acceptance Criteria

- `knowledge/manifest.py`: `PackManifest{id, version, doctor_compat,
  provides, requires}` strict parse; malformed → listed errors,
  never partial load.
- Compat: engine version checked against pack range (simple semver
  range parser, stdlib); mismatch → pack skipped + UnknownFact +
  listed in `knowledge list` with status.
- Precedence documented: explicit --knowledge dir > project dir >
  builtin; same id twice → conflict surfaced, deterministic winner
  (first in precedence) + warning.
- `knowledge validate <dir>` CLI + tests (malformed, incompatible,
  shadowed, happy).
- pytest/ruff/mypy pass.

# Constraints

- Local files only; stdlib range parser documented.
