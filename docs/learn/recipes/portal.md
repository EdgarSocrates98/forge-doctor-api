# Receita — portal web local do Doctor API

**O quê:** `python scripts/forge_portal.py` sobe uma UI web opcional em
`127.0.0.1` sobre os serviços reais do forge — instalação
(`forge_installkit`), hosts (`forge_hosts`), scan (`scan_project`),
grafo (`graphview.build_view`) e docs — protegida por token de sessão.
**Por que:** a mesma jornada do CLI/MCP num browser — plano → confirmação
→ apply com receipts — para quem prefere ver o estado antes de agir.
É um *script* de checkout, não um verbo do pacote: o boundary proíbe
imports de rede/processos em `src/` e a janela RC veda novos comandos
públicos — mesma classe do `forge_install.py`.
**Quando:** primeira configuração de um projeto, auditoria visual de
findings/grafo, ou demonstração do engine sem decorar comandos.
**Quando não:** automação/CI — use `forge-doctor-api scan`,
`scripts/forge_install.py` ou o servidor MCP; o portal é interativo e
loopback-only, não um serviço de rede.

## Passo a passo

```bash
python scripts/forge_portal.py                 # sobe em 127.0.0.1 e abre o browser
python scripts/forge_portal.py --no-browser    # só imprime a URL com token
python scripts/forge_portal.py --port 8765     # porta fixa (default: livre)
python scripts/forge_portal.py --root DIR      # workspace alvo (default: cwd)
```

O servidor imprime um JSON `{"url": "http://127.0.0.1:PORT/?forge_session=…"}`
— a URL carrega o token de sessão; chamadas à API sem `X-Forge-Session`
recebem `403`.

## Interpretação

- **Install**: `status/plan/apply/repair/uninstall` delegam ao
  `forge_installkit` — plano antes de escrever, confirmação explícita
  (`confirm`), `plan_token` amarra plano→apply.
- **Hosts**: probe real (`forge_hosts`) — `NOT_DETECTED` é honesto,
  launch devolve o comando em vez de executar.
- **MCP**: `mcp/verify` faz o handshake JSON-RPC real — "configurado" ≠
  "verificado".
- **Scan/Graph**: `scan_project` e `build_view` rodam sob demanda no
  workspace alvo — determinístico, offline, sem executar código-alvo.
- **Skills/Agents**: vazio por desenho — o Doctor API não distribui
  catálogo de skills; capability `unsupported`, não zero fabricado.

## Verificação

O receipt de cada tarefa (`tasks`) traz `schema_version`, saída do engine
e `exit_code` — "apareceu na UI" nunca é a prova; o receipt é.

## Limitações

Loopback apenas (não bind `0.0.0.0`). Assets estáticos vendored em
`portal/assets/` com manifest sha256 — sem CDN, sem telemetria, sem
rede. Scan em workspaces grandes segue o custo normal do engine.

## Erros comuns

| Sintoma | Causa | Ação |
|---|---|---|
| `403` na API | header `X-Forge-Session` ausente | usar a URL com `?forge_session=` |
| `PORTAL-PLAN-STALE` | apply sem o `plan_token` do plano | refazer o plan e enviar o token |
| `PORTAL-HOST-ABSENT` | launch de host não detectado | instalar o host ou escolher outro |
| skills/agents vazios | capability `unsupported` por desenho | é o comportamento correto |
