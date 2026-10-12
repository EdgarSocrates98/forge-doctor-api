# Instalação portátil — forge-doctor-api

Instala em qualquer diretório/repositório — sem estrutura prévia exigida.

```bash
cd <qualquer-projeto>
python <forge-doctor-api checkout>/scripts/forge_install.py install --yes --root .                    # escopo projeto (padrão)
python <forge-doctor-api checkout>/scripts/forge_install.py install --root . --dry-run                # planeja sem escrever
python <forge-doctor-api checkout>/scripts/forge_install.py install --yes --root . --profile minimal  # só CLI+MCP+marker
python <forge-doctor-api checkout>/scripts/forge_install.py install --yes --root . --profile full     # skills + agents + todos os hosts
python <forge-doctor-api checkout>/scripts/forge_install.py install --yes --root . --gateway-profile economy  # menor custo
```

O que acontece: assets gerenciados vão para `.agents/`, `.claude/`,
`.devin/`, `.codex/` conforme os hosts detectados; `.mcp.json` ganha uma
entrada gerenciada; `AGENTS.md` recebe um bloco delimitado
`<!-- forge-doctor-api:managed -->` — conteúdo seu nunca é sobrescrito.

Perfis: `minimal` (essencial) · `recommended` (workflow completo, padrão)
· `full` (teto de disclosure — não é autorização extra).

Perfis de execução: `economy` reduz custo e contexto; `balanced` é padrão;
`deep` amplia capacidade para tarefas difíceis. Valor fica no recibo e é
preservado quando instalação chega por roteamento do The Forge.
