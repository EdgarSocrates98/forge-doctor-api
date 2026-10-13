---
id: 036-deterministic-gate
title: Deterministic integration gate — byte-identical replay tests
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §7 and §8.
- Problem: determinism is a model-level property tested per-model;
  there is no end-to-end proof that `scan` + all export formats are
  byte-identical across repeated runs on the same input.
- Out of scope: fuzzing, golden-master per-fixture snapshots (fragile);
  benchmarking (spec 043/065).
- Review failure: a test that compares models in memory instead of
  serialized exports; a test that injects different clocks per run and
  calls it determinism.
- Riskiest assumption: exports contain no wall-clock — RESOLVED:
  exports carry schema/tool/knowledge versions only; inject a fixed
  clock where a timestamp is required (policy `today`).
- Smallest acceptable: one integration test running the full pipeline
  twice on a mixed fixture, asserting byte-identical JSON/JSONL/agent/
  SARIF/graph outputs.

# Context

§7: same input + same clock + same config → same semantic output,
ideally byte-for-byte, across JSON, JSONL, agent format, graph,
handoff. §8 makes the offline guarantee part of the same gate class.

# Acceptance Criteria

- `tests/test_determinism.py`: builds a fixture dir (openapi + fastapi
  source + OTLP + k8s + gateway + cache config + policies + clients)
  via tmp_path; runs `scan_project` + unified report twice; asserts
  identical bytes for write_json/write_jsonl/write_agent/write_sarif
  and graph serialization; asserts identical `DoctorReport.to_json()`
  (once spec 039 lands — coordinate or implement against ScanReport
  until then).
- Handoff bundle export included in the byte-identity assertion.
- A deliberately unordered filesystem order (files written in
  different order) still produces identical output.
- Runs under the socket-block fixture from test_offline.py.
- pytest/ruff/mypy pass.

# Constraints

- Fixed clock only; never `datetime.now`.
- Compare serialized bytes, not object equality.
