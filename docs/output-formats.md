# Output formats and the CI gate (§174–§178)

Every machine-readable export carries the same three metadata fields:

```json
{
  "schema_version": "1.0",
  "tool_version": "0.2.0",
  "knowledge_versions": {"openapi-versions": "2026.10", "...": "..."}
}
```

`knowledge_versions` pins every bundled knowledge pack used by the
engine, so an export is fully attributable to the rule data that
produced it.

## Formats

### console (default)

Rich tables to stdout. Human-oriented; not a stable format.

### json

```bash
forge-doctor-api scan . --format json [--out report.json]
```

One object: the metadata envelope plus `gate_passed`, `gate_failures`,
`findings`, and `unknowns`. Findings keep their full shape — id, title,
description, severity, confidence, evidence[], entity_ids[],
source_location, remediation, unknowns[].

### jsonl

```bash
forge-doctor-api scan . --format jsonl
```

Line-delimited: the first line is a `{"_meta": true, ...}` metadata
record, then one JSON finding per line. Suitable for streaming
consumers.

### sarif

```bash
forge-doctor-api scan . --format sarif --out results.sarif
```

SARIF 2.1.0 for static/contract findings:

- `runs[0].tool.driver` = name, version, and a `rules[]` entry per check
  id (severity/confidence in `properties`).
- `runs[0].results[]` = one result per location-anchored finding with
  `ruleId`, `level` (CRITICAL/HIGH→error, MEDIUM→warning, LOW/INFO→note),
  `message`, and `locations[].physicalLocation` (`artifactLocation.uri`
  + `region.startLine` when a line exists).
- Findings without a source location are **skipped, not faked** — the
  count is reported under `runs[0].properties.skipped_no_location`, and
  the rule still appears in `driver.rules[]`.

### agent

```bash
forge-doctor-api scan . --format agent
```

A compact line format for agentic consumers:

```text
# schema_version=1.0 tool_version=0.2.0
# knowledge_versions=openapi-versions@2026.10,...
OAS004|LOW|HIGH|operation:openapi:method_path:GET /items:5|GET /items has no operationId
UNKNOWN|subject|what-is-missing
```

`id|severity|confidence|subject[:line]|description` per finding, plus a
`UNKNOWN|` line per `UnknownFact`.

## The gate (§178)

`--fail-on` takes a comma-separated subset of `breaking,security,policy`:

| Category | Fires when |
|---|---|
| `breaking` | Any `ContractChange` classified `BREAKING` (requires `--baseline`). |
| `security` | Any `APISEC###` finding at `HIGH` confidence. |
| `policy` | Any `POLICY###` violation. |

Exit codes: `1` when a category fires, `2` on misconfiguration — e.g.
`breaking` without `--baseline`, or an unknown category name. Findings
at `UNKNOWN` confidence never produce a gate failure; a gate category
missing its required input is an operator error, not a silent pass.

## GitHub Action

`.github/workflows/doctor-scan.yml` runs the same command in CI:

```yaml
- uses: actions/checkout@v4
- uses: actions/setup-python@v5
  with: {python-version: "3.11"}
- run: pip install .
- run: forge-doctor-api scan "$TARGET" --fail-on "$FAIL_ON" --baseline "$BASELINE"
```

Inputs (`workflow_dispatch`): `fail-on` (default `breaking`),
`baseline`, `policy`, `format` (default `console`), `target` (default
`.`). The job runs with read-only permissions and no network access to
external services — the tool itself never needs it.
