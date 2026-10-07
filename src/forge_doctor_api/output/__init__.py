"""§175-§176 output writers — JSON, JSONL, SARIF 2.1.0, agent compact."""

from forge_doctor_api.output.writers import (
    WRITERS,
    write_agent,
    write_json,
    write_jsonl,
    write_sarif,
)

__all__ = [
    "WRITERS",
    "write_agent",
    "write_json",
    "write_jsonl",
    "write_sarif",
]
