# Instalação global (escopo user) — forge-doctor-api

Instala uma vez para todos os projetos do usuário:

```bash
python scripts/forge_install.py install --yes --scope user
```

Escreve a entrada MCP gerenciada (argv absoluto resolvido — nunca PATH
lookup) na config global do host e o estado/ledger do escopo; este forge
hoje não publica mirrors de skills por host (`~/.claude/`, `~/.agents/`). Combinável com instalações de projeto: o nível mais específico
(`project`) sempre prevalece.
