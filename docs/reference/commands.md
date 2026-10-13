# `forge-doctor-api` command reference

Generated from the real CLI parser by `doc_inventory.py` + `doc_reference.py`. Do not hand-edit generated sections — write between `keep:start`/`keep:end` markers. `por que`/`quando` lines come from the curated `command-rationale.json` — edit rationale there, never here. Status vocabulary: `available` unless marked otherwise.

Rationale coverage: **17/17** first-level groups curated in `command-rationale.json`.

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

**para que:** §68 blast radius: changed operation -> clients -> services -> business paths.

- **por que:** blast radius: operação mudada -> clients -> serviços -> caminhos de negócio
- **quando usar:** antes de mudar uma operação: medir quem quebra

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

**para que:** Inspect, diff and check API contracts.

- **por que:** inspeciona, diffs e checa contratos de API
- **quando usar:** trabalhar contratos: inspeção, diff, check

**Syntax**

```text
forge-doctor-api contract
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `contract compatibility`

**para que:** Classify contract changes by compatibility (§16, §160).

- **por que:** inspeciona, diffs e checa contratos de API
- **quando usar:** trabalhar contratos: inspeção, diff, check

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

**para que:** Diff two API contracts (§66).

- **por que:** inspeciona, diffs e checa contratos de API
- **quando usar:** trabalhar contratos: inspeção, diff, check

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

**para que:** Inspect an API contract: documents, operations, schemas, servers, refs.

Metadata surface only — never emits schema bodies or payloads.

- **por que:** inspeciona, diffs e checa contratos de API
- **quando usar:** trabalhar contratos: inspeção, diff, check

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

**para que:** §165 cluster findings into symptom/candidate causes/affected services/unknowns.

- **por que:** agrupa findings em sintoma/causas candidatas/serviços afetados/unknowns
- **quando usar:** transformar um scan em hipóteses organizadas

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

**para que:** Semantic contract diff (§66): typed change events + optional PR summary.

- **por que:** diff semântico de contrato: eventos de mudança tipados + resumo opcional para PR
- **quando usar:** comparar duas versões de contrato com breaking/risky tipados

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

**para que:** §166 render the evidence chain + rule rationale for a finding.

- **por que:** renderiza a cadeia de evidência + racional da regra de um finding
- **quando usar:** entender por que um finding disparou

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

**para que:** Print the semantic fingerprint of a contract (§180).

- **por que:** imprime o fingerprint semântico de um contrato
- **quando usar:** identificar/ancorar um contrato pelo seu fingerprint

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

**para que:** Show the service graph built from contract + implementation + client evidence (§161).

- **por que:** mostra o grafo de serviços construído de contrato+implementação+evidência de client
- **quando usar:** navegar relações de serviço com evidência

**Syntax**

```text
forge-doctor-api graph <target> [json_out] [view] [ui] [no_browser] [port]
```

| argument/flag | required | default | description |
|---|---|---|---|
| `target` | yes | — | Directory with contract + source evidence. |
| `json_out` | no | — | JSON output. |
| `view` | no | — | Emit ForgeGraphView/v1 (Graph Studio contract). |
| `ui` | no | — | Open the local Graph Studio explorer. |
| `no_browser` | no | — | Serve without opening a browser (SSH). |
| `port` | no | — | Port to bind (default ephemeral). |

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

## inventory

### `inventory`

**para que:** §159 inventory: services, APIs, operations, protocols, owners.

- **por que:** inventário: serviços, APIs, operações, protocolos, owners
- **quando usar:** primeiro mapa de um estate de APIs

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

**para que:** Knowledge-pack manifests, compat and precedence.

- **por que:** manifestos de knowledge-pack, compat e precedência
- **quando usar:** consultar fontes versionadas e sua precedência

**Syntax**

```text
forge-doctor-api knowledge
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `knowledge list`

**para que:** List pack manifests with lifecycle status.

Precedence: explicit dirs > project .forge-doctor/knowledge > builtin.

- **por que:** manifestos de knowledge-pack, compat e precedência
- **quando usar:** consultar fontes versionadas e sua precedência

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

**para que:** Strict-validate one knowledge manifest.

- **por que:** manifestos de knowledge-pack, compat e precedência
- **quando usar:** consultar fontes versionadas e sua precedência

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

**para que:** §199-§201 Forge Lab: run every scenario + report per-family precision.

- **por que:** Forge Lab: roda todos os cenários + relatório de precisão por família
- **quando usar:** validar a ferramenta offline contra ground truth

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

**para que:** §216 serve the Doctor over MCP (requires the `mcp` extra).

- **por que:** serve o Doctor via MCP (requer o extra `mcp`)
- **quando usar:** integrar o doctor a hosts via MCP

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

**para que:** Plugin manifests, registry and conformance.

- **por que:** manifestos de plugin, registry e conformance
- **quando usar:** inspecionar/validar plugins externos

**Syntax**

```text
forge-doctor-api plugins
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `plugins inspect`

**para que:** §52 manifest + compat + rejection reasons for one plugin.

- **por que:** manifestos de plugin, registry e conformance
- **quando usar:** inspecionar/validar plugins externos

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

**para que:** §52 list discovered plugin manifests + rejection reasons.

- **por que:** manifestos de plugin, registry e conformance
- **quando usar:** inspecionar/validar plugins externos

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

**para que:** §54 compat check + conformance preflight (never imports UNTRUSTED).

- **por que:** manifestos de plugin, registry e conformance
- **quando usar:** inspecionar/validar plugins externos

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

**para que:** Reliability analysis.

- **por que:** análise de confiabilidade
- **quando usar:** avaliar resiliência/SLO com evidência

**Syntax**

```text
forge-doctor-api reliability
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `reliability inspect`

**para que:** Passive reliability inspection of declared config (§164).

- **por que:** análise de confiabilidade
- **quando usar:** avaliar resiliência/SLO com evidência

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

**para que:** Reliability along an explicit call path (§164, §228).

- **por que:** análise de confiabilidade
- **quando usar:** avaliar resiliência/SLO com evidência

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

**para que:** Analyze exported runtime evidence.

- **por que:** analisa evidência de runtime exportada
- **quando usar:** trabalhar dumps de runtime offline

**Syntax**

```text
forge-doctor-api runtime
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `runtime baseline`

**para que:** Build runtime baselines (§36, §88, §162).

- **por que:** analisa evidência de runtime exportada
- **quando usar:** trabalhar dumps de runtime offline

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

**para que:** Detect runtime regressions against baselines (§37, §162).

- **por que:** analisa evidência de runtime exportada
- **quando usar:** trabalhar dumps de runtime offline

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

**para que:** Summarize normalized request executions (§28, §162).

- **por que:** analisa evidência de runtime exportada
- **quando usar:** trabalhar dumps de runtime offline

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

**para que:** §177 full scan: every deterministic pipeline + optional §178 gate.

- **por que:** scan completo: todos os pipelines determinísticos + gate opcional
- **quando usar:** primeira passada num repo — produz findings

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

**para que:** Passive security analysis.

- **por que:** análise de segurança passiva
- **quando usar:** revisar postura de segurança declarada sem tocar o serviço

**Syntax**

```text
forge-doctor-api security
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `security inspect`

**para que:** Passive security inspection (§163) - contract/config evidence only.

- **por que:** análise de segurança passiva
- **quando usar:** revisar postura de segurança declarada sem tocar o serviço

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

**para que:** Temporal snapshots + architectural regressions.

- **por que:** snapshots temporais + regressões arquiteturais
- **quando usar:** comparar o estado da arquitetura ao longo do tempo

**Syntax**

```text
forge-doctor-api snapshot
```

<!-- keep:start -->
_free notes — errors, examples, next steps (hand-written, preserved)_
<!-- keep:end -->

### `snapshot diff`

**para que:** Delta context between two snapshots (spec-049 delta).

- **por que:** snapshots temporais + regressões arquiteturais
- **quando usar:** comparar o estado da arquitetura ao longo do tempo

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

**para que:** List stored snapshots (never creates the store).

- **por que:** snapshots temporais + regressões arquiteturais
- **quando usar:** comparar o estado da arquitetura ao longo do tempo

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

**para que:** Evidence-backed architectural regressions a -> b.

- **por que:** snapshots temporais + regressões arquiteturais
- **quando usar:** comparar o estado da arquitetura ao longo do tempo

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

**para que:** Scan the project and store a snapshot under .forge-doctor/.

- **por que:** snapshots temporais + regressões arquiteturais
- **quando usar:** comparar o estado da arquitetura ao longo do tempo

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
