# Forge Doctor API — trilha de aprendizado

| Nível | Caminho |
|---|---|
| **Iniciante** | [Quickstart](../installation/quickstart.md) → [first-run](../tutorials/first-run.md) → receita [scan completo](recipes/scan-contract.md) |
| **Intermediário** | [scan](recipes/scan-contract.md) → [diff semântico](recipes/contract-diff.md) → [diagnose/explain](recipes/diagnose-explain.md) |
| **Avançado** | `lab`/`inventory`/`graph`/`blast-radius` → `security`/`reliability`/`runtime` → `mcp` server |
| **Contribuidor** | [CONTRIBUTING](../../CONTRIBUTING.md) → §-referências no código → `forge-doctor-api lab` |
| **Agente (IA)** | [AGENTS](../../AGENTS.md) → `forge.agentic.json` workflows (`scan`, `diagnose`) → `--format agent` |

## Receitas (problema → solução)

| Tenho este problema | Receita |
|---|---|
| "Auditoria determinística completa do serviço" | [scan-contract](recipes/scan-contract.md) |
| "O que mudou semanticamente no contrato?" | [contract-diff](recipes/contract-diff.md) |
| "Os findings formam qual sintoma?" | [diagnose-explain](recipes/diagnose-explain.md) |
| "Primeiro contato com o Doctor API" | [primeiro-uso](recipes/primeiro-uso.md) |
| "Como instalo num projeto?" | [instalar-doctor-api](recipes/instalar-doctor-api.md) |
| "Interface web local opcional?" | [portal](recipes/portal.md) |
| "Inspecionar um openapi.yaml" | [openapi-contrato](recipes/openapi-contrato.md) |
| "O que essa mudança afeta?" | [graph-blast](recipes/graph-blast.md) |
| "Segurança/timeout declarado aguenta?" | [security-reliability](recipes/security-reliability.md) |
| "Uso pelo Devin/Claude/Codex?" | [mcp-hosts](recipes/mcp-hosts.md) |
| "Doctor API ou API Forge?" | [diferenca-apiforge](recipes/diferenca-apiforge.md) |
| "Comparar estados/regressões?" | [snapshots-history](recipes/snapshots-history.md) |

Hub do ecossistema (descoberta cross-forge): `the-forge/docs/hub/` — install, which-forge, hosts, MCP, troubleshooting.

Índice gerado: [../INDEX.md](../INDEX.md).
