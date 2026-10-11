# Receita — usar o Doctor API pelo seu host de IA (Devin/Claude/Codex)

**O quê:** `forge-doctor-api mcp` serve o catálogo de tools via MCP
(extra `mcp`); `scripts/forge_hosts.py` observa os CLIs de host e abre um
no repo.
**Por que:** "revise os contratos e ache problemas de compatibilidade" deve
ser respondida pelo host chamando `get_contract`/`get_breaking_changes`/
`get_blast_radius` — tools reais, não comandos decorados.
**Quando:** depois de `forge_install.py install --yes`, trabalhando dentro
do Devin/Claude/Codex.
**Quando não:** batch/CI — aí é `scan --format json` direto.

## Passo a passo

```bash
python scripts/forge_hosts.py                  # estado observado dos 4 hosts
python scripts/forge_hosts.py devin            # um host: binário, versão, auth, integração
python scripts/forge_hosts.py devin --launch   # abre o Devin neste repo (TTY)
python scripts/forge_install.py mcp-verify     # handshake real com o servidor MCP
forge-doctor-api mcp .                         # servidor stdio (o host chama)
```

Dentro do host, peça em linguagem natural: *"use get_breaking_changes entre
o contrato publicado e este PR e me diga o que quebra"*.

## Interpretação

`forge_hosts.py` retorna `NOT_DETECTED|SUPPORTED|NEEDS_LOGIN|READY` por
host + `launch_command` + integração. `READY` = logado + instalação
saudável. `NEEDS_LOGIN` vem com o `login_hint` oficial — credencial nunca
é pedida pelo Doctor.

## Verificação

A cadeia real: `forge_install.py install --yes` → `mcp-verify` PASS →
`forge_hosts.py` READY → host lista `forge-doctor-api` entre os servidores.

## Limitações

`forge_hosts.py` vive no checkout, não no pacote: o boundary do Doctor
proíbe `subprocess` em `src/` — observar host é preocupação do checkout,
nunca do engine. Por isso não há tool MCP de hosts aqui: o servidor do
Doctor é puro. `--launch` é fronteira humana (TTY); `copilot` reporta
`logged_in: null` (sem subcomando documentado).

## Erros comuns

| Sintoma | Causa | Ação |
|---|---|---|
| `NEEDS_LOGIN` | host deslogado | rode o `login_hint` |
| `NOT_DETECTED` | CLI fora do PATH | instale o host |
| `launch_refused: no_tty` | `--launch` sem terminal | rode o `launch_command` à mão |
| `mcp` não sobe | extra ausente | `pip install .[mcp]` |

## Uso por agentes

Tools MCP do catálogo: `get_service`, `get_api`, `get_operation`,
`get_contract`, `get_clients`, `get_breaking_changes`, `get_blast_radius`,
`get_runtime_baseline`, `get_regressions`, `get_security_findings`,
`get_reliability_status`, `get_unknowns`.
