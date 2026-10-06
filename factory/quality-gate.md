# Quality Gate Checklist — forge-doctor-api v0.1

Spec 030 requires this checklist plus a recorded run before the v0.1
stabilization spec can be archived. Evidence lives under `factory/runs/`.

## Gate items

- [x] `python -m pytest -q` — all tests pass (incl. offline-blocked sockets)
- [x] `python -m ruff check .` — lint clean
- [x] `python -m mypy src` — strict typecheck clean
- [x] `python -m build` — wheel + sdist build; knowledge packs ship in wheel
- [x] `forge-doctor-api scan .` self-scan runs offline (record:
      `factory/runs/doctor-self-scan-v0.1.json`)
- [x] Output writers: console/JSON/JSONL/SARIF 2.1.0/agent all carry
      `schema_version`, `tool_version`, `knowledge_versions` (§174–176)
- [x] CI gate: `.github/workflows/doctor-scan.yml` with `fail-on`,
      `baseline`, `policy`, `format`, `target` inputs; exit 1 on gate fail,
      2 on misconfiguration (§177–178)
- [x] Gate semantics: `breaking` requires `--baseline`, `security` requires
      HIGH-confidence findings, `policy` triggers on POLICY violations;
      UNKNOWN-confidence findings never block (§178)
- [x] §147 org error-contract evaluation in
      `checks/drift/error_contract.py` (RFC 7807 preset + custom contracts)
- [x] Scale proof: `factory/benchmarks/scale_benchmark.py` record at
      `factory/runs/scale-benchmark.json` (100/1k/10k endpoints,
      10k/100k/1M spans)
- [x] Compact history storage; raw spans never retained by default
      (`keep_spans=False` drop proof in `tests/test_offline.py`)
- [x] Python 3.11/3.12/3.13 classifiers declared; no OS-specific imports
- [x] Version stays `0.1.0`; no registry publish; no 1.0 API commitment

## Record

Run record: `factory/runs/quality-gate-v0.1.json`
