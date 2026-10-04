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

explanation = doctor.explain("OAS001") # finding + evidence + why
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
