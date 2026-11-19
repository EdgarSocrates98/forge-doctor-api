# forge-doctor-api + Codex CLI

```bash
cd ~/meu-projeto
python scripts/forge_install.py install --yes
```

A instalação escreve blocos gerenciados `forge:*` em `AGENTS.md` +
`AGENT_PROTOCOL.md` e o registro `.forge/context/`. Este forge hoje não
publica mirrors em `.codex/` nem `.agents/` — o recibo diz exatamente o
que foi escrito.

MCP: `.mcp.json` gerenciado registra o argv **absoluto** resolvido
(shim do bootstrap ou `python -m forge_doctor_api mcp`). Nota observada:
o Codex CLI não lê `.mcp.json` de projeto em algumas versões — o recibo
marca `mcp-scope:codex` como `NOT_APPLICABLE` nesses casos; MCP entra por
`--scope user` ou `codex mcp add`.
