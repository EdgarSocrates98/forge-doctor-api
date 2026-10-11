# FASE 6 — forge-doctor-api: relatório de experiência

> Objetivo da fase: entregar uma experiência simples de diagnóstico de APIs
> orientado a resultados — agent-first, TUI operacional, instalação auditável,
> observação honesta de hosts e E2E real.

## Estado

**Concluída.** Evidência abaixo.

## O que foi implementado

### 1. Hosts AI (`scripts/forge_hosts.py`)

Observação e lançamento de hosts AI no nível checkout (fora do boundary AST-puro
de `src/`, seguindo o padrão já usado por `forge_install.py`):

- Detecta binário via `shutil.which`, lê versão e estado de autenticação.
- `claude` → `claude auth status`; `devin` → `devin auth status`;
  `codex` → `codex login status`; `copilot` → auth declarada `unknown`
  (não há subcomando de status documentado — honesto).
- Integração lida do ledger de instalação (`unverified` quando não há evidência).
- Lançamento recusado com razões nomeadas: `host_absent`, `login_required`,
  `no_tty`, `select_one_host` (quando `--all`).
- Nenhum caminho de credencial nem saída bruta de auth vai para o recibo.
- `mcp-verify`/`mcp list` são read-only: o launch vive no CLI com TTY.

### 2. TUI (`src/forge_doctor_api/ui/`)

- `_SUSPEND_VERBS` expandido: `analyze`, `judge`, `collect`, `migrate`,
  `graph`, `sdd`, `scan`, `diagnose`, `security`, `reliability`, `contract`,
  `fingerprint`, `inventory`, `snapshot`, `lab`, `diff` — operações reais
  longas/externas rodam anexadas (não capturadas).
- Sentinela `__diff__` no menu: solicita dois caminhos de contrato e executa
  `contract diff old new` de verdade (i18n `diff_old`/`diff_new` em pt-BR e en).
- Teste de contrato do menu: cada argv é validado contra a árvore de comandos
  real do typer (sentinelas `__wizard__`/`__diff__`/`__script__` permitidas
  apenas com handler explícito).

### 3. Installkit (script)

`scripts/forge_installkit.py` sincronizado com a canônica (+13 linhas):
limitação de escopo do Codex registrada como check `NOT_APPLICABLE` no recibo —
`codex` não lê `.mcp.json` de projeto; exige `--scope user` ou `codex mcp add`.

### 4. Documentação PT-BR

Oito receitas novas em `docs/learn/recipes/` (problema → solução → por quê →
quando → quando não → saída esperada → verificação → limitações → erros):

`primeiro-uso`, `instalar-doctor-api`, `openapi-contrato`, `graph-blast`,
`security-reliability`, `mcp-hosts`, `diferenca-apiforge`,
`snapshots-history`.

Docs regenerados (`commands.generated.json`, `commands.md`,
`divergence.generated.json`, `index.md`, knowledge-program) — divergência zero.

### 5. Baseline RC

`docs/rc-baseline.json` re-selado: 87 arquivos de teste (o novo
`test_forge_hosts.py`), 28 comandos CLI, 17 tools MCP.

## Testes

| Slice | Resultado |
|---|---|
| `test_forge_hosts.py` (novo) | 9 passed — host ausente, ready, signed-out recusa launch, no-TTY recusa, launch TTY com exit code, `--all` observe-only, host desconhecido, copilot auth unknown |
| `test_ui_tui.py` | contrato de menu vs parser real |
| `test_forge_install.py` + install/UI/docs | 38 passed |
| `test_rc_baseline.py` | 5 passed (counts, --check, determinismo) |
| ruff | limpo (3 pré-existentes corrigidos) |
| **Suíte integral** | **1763 passed, 37 skipped, 0 failed** em 167.7s (junitxml) — skips são extras opcionais (`graphql` ausente; capability gap explícito) |

## E2E real (scratch `fda-e2e`)

Fixture: repo git com OpenAPI v1/v2, app FastAPI e cliente `httpx`.

| Passo | Evidência |
|---|---|
| `forge_install.py install --yes` | `completed`; `status` → `healthy` |
| `scan .` | **21 findings reais** — `APISEC001` (object-id sem auth), `APISEC011`, `DRIFT001` (operação documentada sem implementação) |
| `diff api/v1 api/v2` | **2 BREAKING reais** — `POST /products` removido; `param id` string→integer, com cadeia de evidência |
| `blast-radius` | clientes afetados: `web`; `unknown` honesto onde falta evidência |
| `snapshot save/list/diff` | rev gravada, diff estrutural JSON correto |
| `diagnose .` | `episodes` + `unknowns` estruturados |
| `explain . <finding>` | desambiguação honesta entre 2 findings homônimos |
| `forge_hosts.py` | claude/devin/codex `READY`, copilot `NOT_DETECTED` |
| `forge_install.py mcp-verify` | `healthy` — handshake real, **17 tools**, invoke `doctor.get_reliability` PASS |
| `devin mcp list` | server `forge-doctor-api` registrado nativamente |
| Mirrors | `.mcp.json`, `AGENTS.md`, `.forge-doctor-api/` no scratch |

### Nota de ambiente

O primeiro `mcp-verify` falhou honestamente: o venv não tinha o extra `mcp`
(`ModuleNotFoundError` reportado no recibo, não escondido). Após
`uv pip install 'mcp>=2.0,<3'` o handshake passou — dependência opcional
explícita no `pyproject.toml`.

## Limitações honestas

- Copilot: autenticação `unknown` — sem comando de status documentado.
- Codex: MCP em escopo de projeto não se aplica (`.mcp.json` não é lido) —
  check `NOT_APPLICABLE` no recibo; usar `--scope user` ou `codex mcp add`.
- `blast-radius` reporta `unknown` para vínculos sem evidência estática —
  não fabrica correlação.
- Integração de hosts fica `unverified` sem ledger de instalação.

## Commits

Ver `git log` — scripts/hosts + installkit sync + TUI + i18n + testes +
8 receitas + regen de docs + re-selo do rc-baseline.
