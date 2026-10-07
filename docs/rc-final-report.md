# RC-hardening final report

Program `prompt_evo_rc_hardening.md` (phases 1–11, specs 081–091),
branch `rc-hardening/081-091`. Every number below names the command
or committed artifact that produces it — nothing is asserted without
a source.

## Identity

| Field | Value | Source |
| --- | --- | --- |
| Initial HEAD | `0ca567f` (`fix(ci): move dependency-review tolerance to step level`) | `git merge-base`/log |
| Final HEAD | tip of `rc-hardening/081-091` — recorded in `factory/artifacts/release-manifest.json` `git.head` and the wave's last commit | `git log` |
| Version | `0.1.0` → `0.2.0` | `pyproject.toml`, `version_gate.py` |

## Tests before / after

| Point | Passing | Source |
| --- | --- | --- |
| Program start (post-080) | 1438 | `docs/release-evidence.md` wave record |
| Spec 083 close | 1556 | session run |
| Spec 085 close | 1666 | session run |
| Spec 087 close | 1711 | session run |
| Spec 088 close | 1745 | session run |
| Final (spec 090) | **1766** | `python -m pytest -q` |

Test files: 74 → 81 (`docs/rc-baseline.json` `test_file_count`,
before = `git show 8402d5f:docs/rc-baseline.json`).

## CI matrix

`.github/workflows/quality.yml`: minimal install (Python 3.11, no
extras) + full install (3.11 / 3.12 / 3.13, `[graphql,mcp]`).
Full leg now also runs `version_gate`, `release_manifest --check`,
`provenance`, `self_scan --check`, and the clean-venv
`release_smoke` (spec 089). `.github/workflows/release.yml` gates
the release itself.

## Lab metrics

54/54 scenarios pass — `forge-doctor-api lab` (was 53 pre-program;
the multi-repo workspace scenario was added by spec 085).

## Real OSS corpus before/after

16 → **31 provenance-pinned slices**, 7 → **14 negatives** —
`docs/rc-baseline.json` `oss_slice_count`/`oss_negative_count`,
`tests/test_oss_corpus.py` (123 tests). Framework/protocol
diversity: OpenAPI, AsyncAPI, GraphQL, gRPC, Kong deck, Envoy,
K8s Gateway API, K8s Ingress, Istio mesh, Spring, Express, NestJS —
`docs/corpus.md`.

## Contract conformance

`forge-contracts/1` vendored models + schemas + validator +
adapters; canonical fixtures under `tests/fixtures/contracts/
canonical/`; 89 conformance tests (`test_contract_conformance.py`)
incl. cross-doctor canonical-payload fixtures (spec 082).
`x-forge-api` registry: 6 keys, bidirectional gate — emitting an
unregistered key or documenting an unemitted one fails
`test_x_forge_api_registry_matches_emitted_keys`.

## MCP hardening

17 tools frozen in `factory/artifacts/mcp-inventory.json`
(`mcp_inventory.py --check`); stable error matrix, bounded payload
limits, malformed-stdio resilience — 19 tests
(`test_mcp_boundary.py`); wheel-installed stdio handshake via
`factory/mcp_smoke.py`.

## Plugin boundary hardening

AST import gate (`plugins/trust.py` — no plugin code is ever
imported to inspect it), `plugins/validation.py` output-shape
validation, failure matrix + no-network/no-mutation proofs —
32 tests (`test_plugin_boundary.py`).

## Runtime benchmark + memory curves + snapshot scale

Measured envelope (this host, tracemalloc; committed baseline
`factory/runs/scale-benchmark.json`, full table in
`docs/release-evidence.md` / `docs/runtime-scale.md`):

| Kind | Scale | Wall (s) | Peak (MB) |
| --- | --- | --- | --- |
| endpoints | 10,000 | 41.6 | 107.6 |
| spans grouped | 100,000 | 132.3 | 128.0 |
| spans churn | 100,000 | 193.9 | 184.0 |
| snapshot suite | 10k+10k | scan 681.8 / load 121.5 | 388.2 |

Memory stays linear-with-window; churn evictions, late spans, and
tombstone overflow are all accounted. Two real bugs found and fixed
by the work itself: self-parented span-id cycle hang
(`_critical_path`) and heterogeneous-`tuple` snapshot decode.

## Compatibility rule improvements

Spec 087 (`tests/test_compat_adversarial.py`, 41 tests;
`docs/compatibility.md`): OpenAPI `nullable` flips (incl.
key-removal ⇒ `false`) and discriminator changes; GraphQL union
membership + directive-set diffs (`GQL011–013`); gRPC enum
renumbering + oneof membership (`GRPC008–009`); new AsyncAPI compat
engine `analyzers/asyncapi/compat.py` (`ASYNC009–017`); client
extractors for Java Feign, generated OpenAPI clients, gRPC stubs,
GraphQL documents; `ClientCallSite.operation`.

## Security/reliability precision changes

Spec 088 (`tests/test_sec_rel_adversarial.py`, 33 tests;
`docs/security-reliability.md`): implementation authz now includes
route-middleware evidence (`AuthorizationPolicy.via`); gateway
`prefix`/`path` scopes bind to operations; unresolved security
schemes stay `unknown` (APISEC011 owns ambiguity; APISEC013 no
longer fabricates chain breaks); config walkers skip
`examples`/`properties`-style non-evidence keys; cache graph joins
require declared subjects/keys with partition guards;
`CacheGraph.unknowns` propagate into scan reports.

## Release artifact set

`dist/` wheel + sdist, `SHA256SUMS`, `sbom.cdx.json`,
`factory/artifacts/release-manifest.json` (identity + digests),
`factory/artifacts/provenance.json` (in-toto-lite),
`factory/runs/doctor-self-scan.json` dogfood baseline.
Gates: `version_gate.py`, `release_manifest.py --check`,
`self_scan.py --check`, `release_smoke.py` — all wired into the
full CI leg.

## Versioning decision

`0.1.0` → `0.2.0`, owner-authorized, "Trusted Unified Doctor" phase
marker — full rationale and `1.0` triggers in
[versioning.md](versioning.md). No `1.0`, no publish, no tag.

## Known limitations

- **No downstream consumer proof yet** — the `1.0` trigger (a Data
  Doctor/Forger release consuming `forge-contracts/1` unchanged) is
  still open; cross-doctor fixtures are canonical, not captured
  upstream output.
- **Corpus slices are single files** — real repos with
  multi-file/multi-module layout are not yet vendored.
- **Java client extraction is regex-based** — nested/computed
  annotations beyond the covered patterns go unknown.
- **Snapshot load is slow at recorded scale** — 121.5s for an
  18.8MB report; recorded, not gated.
- **Config walkers trust the non-evidence key list** — new YAML
  narrative keys must be added to `_NON_EVIDENCE_KEYS` or they can
  fabricate policies.
- **Self-scan findings are informational** — 826 findings / 33
  unknowns on the repo itself; the gate pins *shape*, not zero.
- **`dirty_tree` in the committed manifest** reflects build-time
  state by design (volatile field; `--check` excludes git state).
- **Publish stays manual** — release workflow is human-gated by
  policy, not yet automated end-to-end.

## Next blockers

1. Land a real downstream consumer (`forge-contracts/1` payload
   consumed unchanged) — gates `1.0`.
2. Keep CLI/check surfaces additive-only for a full cycle — the
   drift gates are already armed.
3. Multi-file real-repo corpus slices (monorepo layouts).
4. Snapshot load performance if recorded scale grows.
