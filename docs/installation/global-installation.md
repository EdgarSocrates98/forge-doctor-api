# Instalação global (escopo user) — forge-doctor-api

Instala uma vez para todos os projetos do usuário:

```bash
python scripts/forge_install.py apply --scope user
```

Escreve em `~/.claude/`, `~/.agents/`, `~/.config/<host>/` e config MCP
global. Combinável com instalações de projeto: o nível mais específico
(`project`) sempre prevalece.
