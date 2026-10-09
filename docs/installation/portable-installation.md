# Instalação portátil — forge-doctor-api

Instala em qualquer diretório/repositório — sem estrutura prévia exigida.

```bash
cd <qualquer-projeto>
python <forge-doctor-api checkout>/scripts/forge_install.py apply --root .                    # escopo projeto (padrão)
python <forge-doctor-api checkout>/scripts/forge_install.py apply --root . --dry-run          # planeja sem escrever
python <forge-doctor-api checkout>/scripts/forge_install.py apply --root . --profile minimal  # só CLI+MCP+marker
python <forge-doctor-api checkout>/scripts/forge_install.py apply --root . --profile full     # skills + agents + todos os hosts
```

O que acontece: assets gerenciados vão para `.agents/`, `.claude/`,
`.devin/`, `.codex/` conforme os hosts detectados; `.mcp.json` ganha uma
entrada gerenciada; `AGENTS.md` recebe um bloco delimitado
`<!-- forge-doctor-api:managed -->` — conteúdo seu nunca é sobrescrito.

Perfis: `minimal` (essencial) · `recommended` (workflow completo, padrão)
· `full` (teto de disclosure — não é autorização extra).
