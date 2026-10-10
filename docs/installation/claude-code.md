# forge-doctor-api + Claude Code

```bash
cd ~/meu-projeto
python scripts/forge_install.py install --yes
```

Assets vão para `.claude/skills/`; `CLAUDE.md` recebe o bloco gerenciado
apenas se já existir (nunca criado sem pedido). Abra o Claude Code no
diretório — as skills aparecem automaticamente.

MCP: `claude` lê `.mcp.json` da raiz — a entrada `forge-doctor-api mcp` é registrada na instalação.
