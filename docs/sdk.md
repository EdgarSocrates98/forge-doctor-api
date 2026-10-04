# Python SDK

The `Doctor` facade is the stable public surface of forge-doctor-api.
Everything behind it is deterministic and offline: same input, same
`clock`, same bytes out.

```python
from forge_doctor_api import Doctor

doctor = Doctor.from_path("services/orders", clock=None)

report = doctor.scan()                 # DoctorReport (unified)
before = Doctor.from_path("snapshots/orders-v1")
diff_report = doctor.scan(before)      # contract diff + impact
diff2 = doctor.diff(before)            # alias

explanation = doctor.explain("OAS001") # finding + evidence + rule +
                                       # why + unknowns + next_evidence
graph = doctor.graph()                 # DomainSummary | None
bundle = doctor.handoff()              # ApiHandoffBundle V2
inventory = doctor.inventory()         # ArtifactInventory
caps = doctor.capabilities()           # detected capabilities
slice_ = doctor.slice("doctor://service")
```

## Errors

Bad input raises typed `DoctorError` subclasses, never bare tracebacks:

- `ProjectUnreadableError` — missing path, not a directory, unreadable
- `FindingNotFoundError` — `explain` target absent from the report

## Import contract

`forge_doctor_api.__all__` is the curated public surface (snapshot-
tested): `Doctor`, `DoctorReport`, core models (`Finding`,
`UnknownFact`, `Evidence`, `SourceLocation`, `Severity`,
`Confidence`), `ArtifactInventory`, `AnalysisPlan`, `DomainSummary`,
`ApiHandoffBundle`, the Forge protocol models (`ForgeRequest`,
`ForgeHandoff`, `ForgeReceipt`, `ForgeResult`, `ForgeRef`),
`assemble_bundle`, `ProjectContext`, `SDK_VERSION`, `__version__`.
Deep module imports are internal and may move.

## Explain (spec 066)

`Explanation` carries: the `finding` itself, its `evidence`
summaries, a `why` built from the catalog rule the check is
registered under (`rule` — title/severity/confidence/description
from the shipped check catalogs), the finding's `unknowns`, and
`next_evidence` — the concrete resolutions attached to those
unknowns, i.e. the evidence that would raise confidence if supplied.
`explain` matches by finding id or entity id; unknown ids raise
`FindingNotFoundError`. The same surface is exposed as
`forge-doctor-api explain TARGET FINDING` on the CLI and
`doctor.explain` over MCP.

## Analysis stats (spec 066)

`report.stats` always carries deterministic per-analyzer counters —
which analyzers ran, how many artifacts each consumed, how many
findings/unknowns each emitted — plus totals. Wall-time
(`duration_ms`) and allocation (`allocated_bytes`) fields exist only
when the caller passes `stats_timing`/`--stats-timing` and are
excluded from the canonical report hash.

## Incremental scans (spec 065)

`scan_project(..., incremental=True)` / `--incremental` reuses
analyzer-level models from `.forge-doctor/cache/` (keys: artifact
sha256 + analyzer + tool version + config digest). Findings and
checks always recompute; cold and warm outputs are byte-identical.
The cache is never created without the flag.
