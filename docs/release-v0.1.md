# Release stabilization — v0.1

Spec 030 acceptance evidence. The checklist lives in
`factory/quality-gate.md`; this page explains what each gate means.

## Verification commands

```bash
python -m pytest -q        # 1000+ tests, sockets hard-blocked
python -m ruff check .     # lint
python -m mypy src         # strict typecheck
python -m build            # wheel + sdist into dist/
```

## Hermetic / offline guarantees

- No `socket`/`urllib`/`http`/`requests`/`httpx`/`subprocess` imports in
  `src/` — enforced by `tests/test_package.py`.
- `tests/test_offline.py` monkeypatches socket constructors to raise —
  scans still pass.
- Every filesystem read goes through `ProjectContext`
  (`iter_files`, `read_text`, `resolve`) so a scan cannot reach outside
  its declared root.
- External `$ref`s are recorded as `UnresolvedExternalRef`, never
  fetched.

## Scale and retention

`factory/benchmarks/scale_benchmark.py` records honest wall-time and
peak-heap numbers at the spec'd scales into
`factory/runs/scale-benchmark.json` (100/1k/10k endpoints,
10k/100k/1M spans on the development host — your numbers will differ;
the record is evidence of scale coverage, not a latency SLA).

Retention: raw spans are dropped by default (`keep_spans=False`);
`RequestHistory` stores summary executions only.

## Packaging

- `python -m build` produces both `forge_doctor_api-0.1.0-py3-none-any.whl`
  and `.tar.gz`; the wheel is verified to contain the knowledge YAML
  packs (`tests/test_packaging.py`).
- Classifiers declare Python 3.11/3.12/3.13 and OS independence; a test
  asserts no platform-only imports (`winreg`, `fcntl`, `msvcrt`, …).
- Version stays `0.1.0`. Nothing is published to a registry, and no 1.0
  public-API commitment is made.

## Dogfood

`forge-doctor-api scan .` runs on this repository itself; the recorded
result lives at `factory/runs/doctor-self-scan-v0.1.json`. Findings
there land on the `labs/` fixtures (intentionally broken contracts) —
and the self-scan caught a real AsyncAPI entity-id bug during
development.
