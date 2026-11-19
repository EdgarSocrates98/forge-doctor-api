# forge-doctor-api + Devin CLI

```bash
cd ~/meu-projeto
python scripts/forge_install.py install --yes
```

A instalação escreve blocos gerenciados `forge:*` em `AGENTS.md` +
`AGENT_PROTOCOL.md` e o registro `.forge/context/`. Este forge hoje não
publica mirrors em `.devin/` nem `.agents/` — a superfície declarada é a
real.

MCP: a entrada gerenciada em `.mcp.json` registra o argv **absoluto**
resolvido na instalação (shim do bootstrap ou
`python -m forge_doctor_api mcp`) — o host nunca lança por PATH lookup.
