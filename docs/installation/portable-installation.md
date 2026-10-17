# Instalação portátil — forge-doctor-api

Instala em qualquer diretório/repositório — sem estrutura prévia exigida.

Desde 0.2.0 (ADR-0006, exceção RC registrada em cyc11.2 P2-002) o ciclo de
vida `forge/*` v1 viaja na wheel — o caminho público é a própria CLI:

```bash
cd <qualquer-projeto>
forge-doctor-api install --yes --root .                     # escopo projeto (padrão)
forge-doctor-api install --root . --dry-run                 # planeja sem escrever
forge-doctor-api install --yes --root . --profile minimal   # só CLI+MCP+marker
forge-doctor-api install --yes --root . --profile full      # skills + agents + todos os hosts
forge-doctor-api install --yes --root . --gateway-profile economy  # menor custo
```

Mesmos verbos, mesmos recibos, mesmo ledger: `install status|doctor|repair|
uninstall|update|mcp-verify`. `python -m forge_doctor_api install ...` é a
forma equivalente sem dependência de PATH.

## Delegação — template argv para o catálogo do forge-cli

O catálogo do `forge-cli` (arquivo `src/constants/repos.ts`, fora deste
repositório) deve delegar o método registry/native por módulo:

```text
install:   {python} -m forge_doctor_api install --yes
update:    {python} -m forge_doctor_api install update
uninstall: {python} -m forge_doctor_api install uninstall
```

A forma `{bin}` (`forge-doctor-api install ...`) é equivalente quando o
console script está no PATH; `{python} -m` não exige PATH e é o que os
testes exercitam (`tests/test_install_cli.py`).

## Adapter de checkout

`python <checkout>/scripts/forge_install.py <verbo>` continua válido numa
árvore-fonte antes de qualquer wheel existir — mesmos verbos e recibos,
mesmo engine vendored (`_installkit`, byte-parity garantida por
`test_package_carries_install_surface`). Numa instalação via wheel, a
delegação acima é o caminho suportado.

O que acontece: assets gerenciados vão para `.agents/`, `.claude/`,
`.devin/`, `.codex/` conforme os hosts detectados; `.mcp.json` ganha uma
entrada gerenciada; `AGENTS.md` recebe um bloco delimitado
`<!-- forge-doctor-api:managed -->` — conteúdo seu nunca é sobrescrito.

Perfis: `minimal` (essencial) · `recommended` (workflow completo, padrão)
· `full` (teto de disclosure — não é autorização extra).

Perfis de execução: `economy` reduz custo e contexto; `balanced` é padrão;
`deep` amplia capacidade para tarefas difíceis. Valor fica no recibo e é
preservado quando instalação chega por roteamento do The Forge.
