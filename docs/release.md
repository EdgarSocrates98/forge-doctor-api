# Release

How releases work, what ships, and why the version is what it is.
Policy details live in [release-policy.md](release-policy.md); the
evidence record for this stabilization program is in
[release-evidence.md](release-evidence.md).

## Version decision — 0.1.x

**Decision: the package stays on the `0.1.x` line.**

`AGENTS.md` forbids a version bump for this program; this entry
records the *why* so the decision survives the session that made it:

- The public contract is young. `forge-contracts/1` (spec 074) and
  the slim `ForgeRequest`/bounded handoff (spec 075) define the wire
  language the Forger ecosystem consumes. Declaring `1.0` freezes
  that surface; the wire needs at least one downstream consumer to
  prove its shape before it is promised stable.
- The `0.x` line carries no stability promise (see
  [release-policy.md](release-policy.md)) — the honest position for a
  package whose check catalogs are still growing.
- **Revisit trigger:** cut `1.0.0` when a `forge-contracts/1` payload
  produced here is consumed unchanged by a Data Doctor / Forger
  release *and* the CLI inventory + check catalog go a full release
  cycle additive-only. Until then, breaking changes land as `0.1.x`
  with changelog notes.

This is a decision record, not a date: `0.1.0` in `pyproject.toml`
is intentional.

## Artifact inventory

Every release emits, via `.github/workflows/release.yml`:

| Artifact | Producer | Purpose |
| --- | --- | --- |
| `forge_doctor_api-<v>-py3-none-any.whl` | `python -m build` | wheel |
| `forge_doctor_api-<v>.tar.gz` | `python -m build` | sdist |
| `sbom.cdx.json` | `factory/sbom.py --out dist/sbom.cdx.json` | CycloneDX 1.5 SBOM from declared deps only |
| `SHA256SUMS` | `sha256sum` / `factory/sha256sums.py` | integrity manifest, sorted by filename |
| `release-manifest.json` | `factory/release_manifest.py --rc` | release identity: version, git HEAD, dirty flag, contract/protocol versions, artifact digests, surface counts |
| `provenance.json` | `factory/provenance.py` | in-toto-lite: builder id, source repo+revision, build commands, subjects |
| build-provenance attestation | `actions/attest-build-provenance` | OIDC-signed provenance |

The release workflow opens a **draft** GitHub release; a human
publishes. It never auto-publishes.

## RC gates (spec 089)

| Gate | Command | Fails when |
| --- | --- | --- |
| Version consistency | `python factory/version_gate.py` | `pyproject.version`, `__init__.__version__`, `sdk.SDK_VERSION`, `release-manifest.json`, and `dist/` filenames diverge |
| Release manifest | `python factory/release_manifest.py --check` | any non-volatile manifest field drifts (git state + artifact digests are compared by shape, not value) |
| Dirty-tree policy | `python factory/release_manifest.py --rc` | refuses `rc: true` on a dirty or unverifiable tree unless `--allow-dirty` |
| Provenance | `python factory/provenance.py` | deterministic in-toto-lite document over `dist/` subjects |
| Release smoke | `python factory/release_smoke.py --extras "[graphql,mcp]"` | clean-venv wheel install fails to serve `--version`, `scan`, `contract inspect`, `lab`, or the MCP handshake |
| Dogfood | `python factory/self_scan.py --check` | the self-scan report's *shape* (finding/unknown identities, gate result, versions) drifts from `factory/runs/doctor-self-scan-v0.1.json`; evidence text and line numbers are whitelisted as volatile |

All gates run in the `full`/`3.12` leg of `quality.yml`; the release
smoke installs only the built wheel, never the source tree.

## Supply-chain note (§22)

Runtime dependencies are declared-only (`typer`, `rich`, `pyyaml`,
plus the `graphql`/`mcp` extras) — no vendored third-party code paths.
The dependency-review workflow annotates PRs where GitHub Advanced
Security is available; on private forks without it, run
`python factory/sbom.py --check` locally — the SBOM is generated from
`pyproject.toml` so undeclared deps cannot hide in it.

## Reproduction

From a clean checkout:

```bash
pip install -e '.[graphql,mcp]' pytest ruff mypy types-PyYAML build
python -m pytest -q                      # test suite
python -m ruff check .                   # lint
python -m mypy src                       # strict types
python -m build                          # wheel + sdist -> dist/
python factory/sbom.py --check           # SBOM matches committed artifact
python factory/sbom.py --out dist/sbom.cdx.json
python factory/sha256sums.py             # emit dist/SHA256SUMS
python factory/sha256sums.py --verify    # re-hash + diff
forge-doctor-api lab --no-record         # lab corpus
python factory/benchmarks/scale_benchmark.py --check   # perf budget
python factory/version_gate.py              # version consistency
python factory/release_manifest.py --rc     # release manifest
python factory/release_manifest.py --check  # drift gate
python factory/provenance.py                # in-toto-lite provenance
python factory/self_scan.py --check         # dogfood baseline
python factory/release_smoke.py --extras "[graphql,mcp]"  # wheel proof
```

The committed reference SBOM lives at
`factory/artifacts/sbom.cdx.json`; `sbom.py --check` regenerates from
`pyproject.toml` and diffs — declaration drift fails the gate.
