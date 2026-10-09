# `forge-doctor-api` command reference

Generated from the real CLI parser by `doc_inventory.py` + `doc_reference.py`. Do not hand-edit generated sections — write between `keep:start`/`keep:end` markers. Status vocabulary: `available` unless marked otherwise.

## Groups

- [`blast-radius`](#blast-radius) — 1 command(s)
- [`contract`](#contract) — 4 command(s)
- [`diagnose`](#diagnose) — 1 command(s)
- [`diff`](#diff) — 1 command(s)
- [`explain`](#explain) — 1 command(s)
- [`fingerprint`](#fingerprint) — 1 command(s)
- [`graph`](#graph) — 1 command(s)
- [`inventory`](#inventory) — 1 command(s)
- [`knowledge`](#knowledge) — 3 command(s)
- [`lab`](#lab) — 1 command(s)
- [`mcp`](#mcp) — 1 command(s)
- [`plugins`](#plugins) — 4 command(s)
- [`reliability`](#reliability) — 3 command(s)
- [`runtime`](#runtime) — 4 command(s)
- [`scan`](#scan) — 1 command(s)
- [`security`](#security) — 2 command(s)
- [`snapshot`](#snapshot) — 5 command(s)

## blast-radius

### `blast-radius`

§68 blast radius: changed operation -> clients -> services -> business paths.

**Syntax**

```text
forge-doctor-api blast-radius <old> <new> [clients] [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `old` | yes | — | Old contract file or directory. |
| `new` | yes | — | New contract file or directory. |
| `clients` | no | — | Directory of client sources. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## contract

### `contract`

Inspect, diff and check API contracts.

**Syntax**

```text
forge-doctor-api contract
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `contract compatibility`

Classify contract changes by compatibility (§16, §160).

**Syntax**

```text
forge-doctor-api contract compatibility <old> <new> [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `old` | yes | — | Old contract file or directory. |
| `new` | yes | — | New contract file or directory. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `contract diff`

Diff two API contracts (§66).

**Syntax**

```text
forge-doctor-api contract diff <old> <new> [semantic] [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `old` | yes | — | Old contract file or directory. |
| `new` | yes | — | New contract file or directory. |
| `semantic` | no | — | Emit the semantic change list. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `contract inspect`

Inspect an API contract: documents, operations, schemas, servers, refs.

Metadata surface only — never emits schema bodies or payloads.

**Syntax**

```text
forge-doctor-api contract inspect <target> [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | yes | — | Contract file or directory. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## diagnose

### `diagnose`

§165 cluster findings into symptom/candidate causes/affected services/unknowns.

**Syntax**

```text
forge-doctor-api diagnose <target> [before] [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | yes | — | Directory with current-state evidence (contract + config + runtime artifacts). |
| `before` | no | — | Prior-state directory for the change diff. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## diff

### `diff`

Semantic contract diff (§66): typed change events + optional PR summary.

**Syntax**

```text
forge-doctor-api diff <old> <new> [semantic] [json_out] [pr] [clients]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `old` | yes | — | Old contract file or directory. |
| `new` | yes | — | New contract file or directory. |
| `semantic` | no | — | Emit typed change events (§65). |
| `json_out` | no | — | JSON output. |
| `pr` | no | — | Print the §67 PR-intel summary. |
| `clients` | no | — | Directory of client sources (blast radius). |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## explain

### `explain`

§166 render the evidence chain + rule rationale for a finding.

**Syntax**

```text
forge-doctor-api explain <target> <finding> [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | yes | — | Directory the finding came from. |
| `finding` | yes | — | Finding id or subject token to explain. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## fingerprint

### `fingerprint`

Print the semantic fingerprint of a contract (§180).

**Syntax**

```text
forge-doctor-api fingerprint <target>
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | yes | — | Contract file or directory. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## graph

### `graph`

Show the service graph built from contract + implementation + client evidence (§161).

**Syntax**

```text
forge-doctor-api graph <target> [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | yes | — | Directory with contract + source evidence. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## inventory

### `inventory`

§159 inventory: services, APIs, operations, protocols, owners.

**Syntax**

```text
forge-doctor-api inventory [target] [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | no | — | Workspace or repo directory. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## knowledge

### `knowledge`

Knowledge-pack manifests, compat and precedence.

**Syntax**

```text
forge-doctor-api knowledge
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `knowledge list`

List pack manifests with lifecycle status.

Precedence: explicit dirs > project .forge-doctor/knowledge > builtin.

**Syntax**

```text
forge-doctor-api knowledge list [dirs] [target]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `dirs` | no | — | Pack dirs, highest precedence first. |
| `target` | no | — | Project dir for .forge-doctor/knowledge. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `knowledge validate`

Strict-validate one knowledge manifest.

**Syntax**

```text
forge-doctor-api knowledge validate <directory>
```

| argument/flag | required | default | description |
|---|---|---|---|
| `directory` | yes | — | Pack dir or toml file. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## lab

### `lab`

§199-§201 Forge Lab: run every scenario + report per-family precision.

**Syntax**

```text
forge-doctor-api lab [target] [json_out] [no_record]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | no | — | Labs corpus directory. |
| `json_out` | no | — | JSON output. |
| `no_record` | no | — | Skip factory/runs record. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## mcp

### `mcp`

§216 serve the Doctor over MCP (requires the `mcp` extra).

**Syntax**

```text
forge-doctor-api mcp [target] [transport]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | no | — | Project directory to serve over MCP. |
| `transport` | no | — | stdio (default). |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## plugins

### `plugins`

Plugin manifests, registry and conformance.

**Syntax**

```text
forge-doctor-api plugins
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `plugins inspect`

§52 manifest + compat + rejection reasons for one plugin.

**Syntax**

```text
forge-doctor-api plugins inspect <plugin_id> [directory]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `plugin_id` | yes | — | Plugin id. |
| `directory` | no | — | Directory scanned for plugin manifests. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `plugins list`

§52 list discovered plugin manifests + rejection reasons.

**Syntax**

```text
forge-doctor-api plugins list [directory]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `directory` | no | — | Directory scanned for plugin manifests. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `plugins verify`

§54 compat check + conformance preflight (never imports UNTRUSTED).

**Syntax**

```text
forge-doctor-api plugins verify <plugin_id> [target] [directory]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `plugin_id` | yes | — | Plugin id. |
| `target` | no | — | Project the plugin analyzes during conformance. |
| `directory` | no | — | Directory scanned for plugin manifests. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## reliability

### `reliability`

Reliability analysis.

**Syntax**

```text
forge-doctor-api reliability
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `reliability inspect`

Passive reliability inspection of declared config (§164).

**Syntax**

```text
forge-doctor-api reliability inspect <target> [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | yes | — | Directory with config artifacts. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `reliability path`

Reliability along an explicit call path (§164, §228).

**Syntax**

```text
forge-doctor-api reliability path <target> [hops] [policy] [timeout] [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | yes | — | Directory with config artifacts. |
| `hops` | no | — | Hop name in call order; repeatable. |
| `policy` | no | — | Inline declared retry: scope=max_attempts; repeatable. |
| `timeout` | no | — | Inline declared timeout: scope=ms; repeatable. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## runtime

### `runtime`

Analyze exported runtime evidence.

**Syntax**

```text
forge-doctor-api runtime
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `runtime baseline`

Build runtime baselines (§36, §88, §162).

**Syntax**

```text
forge-doctor-api runtime baseline <target> [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | yes | — | Directory with runtime artifacts. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `runtime regressions`

Detect runtime regressions against baselines (§37, §162).

**Syntax**

```text
forge-doctor-api runtime regressions <target> [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | yes | — | Directory with runtime artifacts. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `runtime requests`

Summarize normalized request executions (§28, §162).

**Syntax**

```text
forge-doctor-api runtime requests <target> [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | yes | — | Directory with runtime artifacts. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## scan

### `scan`

§177 full scan: every deterministic pipeline + optional §178 gate.

**Syntax**

```text
forge-doctor-api scan [target] [fail_on] [baseline] [policy] [fmt] [out] [stats_timing] [incremental]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | no | — | Project directory. |
| `fail_on` | no | — | §178 gate categories, comma-separated: breaking,security,policy. |
| `baseline` | no | — | Baseline contract file/dir for the breaking gate. |
| `policy` | no | — | Extra policy file/dir merged into evaluation. |
| `fmt` | no | — | console | json | jsonl | sarif | agent | report (full DoctorReport). |
| `out` | no | — | Write the export to a file. |
| `stats_timing` | no | — | Record per-analyzer wall time in report.stats (non-canonical; excluded from deterministic hashing). |
| `incremental` | no | — | Reuse cached analyzer models under .forge-doctor/cache/ (findings always recompute). |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## security

### `security`

Passive security analysis.

**Syntax**

```text
forge-doctor-api security
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `security inspect`

Passive security inspection (§163) - contract/config evidence only.

**Syntax**

```text
forge-doctor-api security inspect <target> [json_out]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | yes | — | Project directory. |
| `json_out` | no | — | JSON output. |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## snapshot

### `snapshot`

Temporal snapshots + architectural regressions.

**Syntax**

```text
forge-doctor-api snapshot
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `snapshot diff`

Delta context between two snapshots (spec-049 delta).

**Syntax**

```text
forge-doctor-api snapshot diff <a> <b> [target]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `a` | yes | — | Snapshot id/label (older). |
| `b` | yes | — | Snapshot id/label (newer). |
| `target` | no | — | — |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `snapshot list`

List stored snapshots (never creates the store).

**Syntax**

```text
forge-doctor-api snapshot list [target]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | no | — | — |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `snapshot regressions`

Evidence-backed architectural regressions a -> b.

**Syntax**

```text
forge-doctor-api snapshot regressions <a> <b> [target]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `a` | yes | — | Snapshot id/label (older). |
| `b` | yes | — | Snapshot id/label (newer). |
| `target` | no | — | — |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `snapshot save`

Scan the project and store a snapshot under .forge-doctor/.

**Syntax**

```text
forge-doctor-api snapshot save [target] [label]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | no | — | Project directory. |
| `label` | no | — | — |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->
