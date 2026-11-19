# forge-doctor-api + Claude Code

```bash
cd ~/meu-projeto
python scripts/forge_install.py install --yes
```

A instalação escreve blocos gerenciados `forge:*` em `AGENTS.md` e
`CLAUDE.md` (compactos — identidade, domínios e ponteiros para
`.forge/context/`; o detalhe de interfaces fica no manifesto e em
`AGENT_PROTOCOL.md`, nunca duplicado no contexto permanente). Este forge
hoje não publica mirrors em `.claude/skills/` — o registro declara o que
existe, nada mais.

MCP: `claude` lê `.mcp.json` da raiz — a entrada gerenciada registra o
argv **absoluto** resolvido na instalação (shim do bootstrap ou
`python -m forge_doctor_api mcp`), nunca um PATH lookup.
