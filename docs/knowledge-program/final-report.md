# Forge Knowledge Program — final report

| Campo | Valor |
|---|---|
| repository | `forge-doctor-api` |
| branch | `feat/knowledge-experience` |
| commit | `89e0025` |
| docs inventoried | 287 (excl. GENERATED mirrors: 282; vendored upstream: 0) |

## Review levels (honest)

- `INVENTORIED`: 0
- `AUTOMATICALLY_CHECKED`: 287
- `TECHNICALLY_VERIFIED`: 0
- `SEMANTICALLY_REVIEWED`: 0
- `USER_JOURNEY_VALIDATED`: 0

Automatic checks ran on every row; semantic review is recorded only where a human/verified pass happened — nothing is inflated.

## Category counts

- `UNKNOWN`: 130
- `HISTORICAL`: 91
- `USER_GUIDE`: 20
- `CONTRACT`: 10
- `TEST_EVIDENCE`: 7
- `RELEASE_REPORT`: 7
- `GENERATED`: 5
- `ADR`: 5
- `ARCHITECTURE`: 3
- `GETTING_STARTED`: 3
- `INTERNAL`: 2
- `AGENT_INSTRUCTIONS`: 1
- `TUTORIAL`: 1
- `HOW_TO`: 1
- `REFERENCE`: 1

## Findings

- duplicate groups (non-generated): 0
- broken internal links total: 0 (active docs: 0; remainder in frozen/historical trees)
- documented-but-missing commands: 0 (active docs: 0)
- undocumented public commands: 0

## Educational layer delivered

- first-run/quickstart docs: 3
- docs/learn/ entries: 4
- docs/hub/ entries: 0

## Documentation changes this program

- `docs/INDEX.md` — generated canonical index (7-section IA)
- `docs/learn/` — learning track + problem-oriented recipes
- `docs/knowledge-program/` — inventory + 8 reports + context map

## Tests / gates

- `tests/test_doc_manifest.py` — zero broken links in active docs (frozen trees exempt)
- `check_docs`/`doc_inventory` — command drift gate, parser-walked

## Limitations & remaining gaps

- Semantic review of the full corpus is not claimed — review levels in `inventory.jsonl` say which docs were actually reviewed.
- Historical/frozen trees keep their broken links by design (§4.5 preservation) — they are reported, not repaired.
- Hub site build not executed (dev-only, `mkdocs-material`); the markdown hub is the verified deliverable.
- Screen-reader and POSIX-terminal validation remain UNVERIFIED on this host.

## Final status: **PASS**
