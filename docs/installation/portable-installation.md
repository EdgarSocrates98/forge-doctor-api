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

## Bootstrap — `--dist`, `--allow-url`, `install.windows.sh` (0.2.3+)

`scripts/forge_bootstrap.py` é a rota de instalação account-level
(`install.sh`/`install.ps1`/`install.windows.sh` chamam ele):

```bash
./install.sh                                  # prefere wheel do checkout
./install.sh --dist "DIST==0.2.5"             # wheel publicada (PyPI/wheelhouse)
./install.sh --dist "DIST[mcp]==0.2.5"        # extras entre nome e spec
./install.sh --dist "DIST @ https://…/x.whl" --allow-url  # URL exige opt-in
./install.windows.sh                          # rota Git Bash/MSYS (sem PowerShell)
```

- `--dist <spec>` instala a distribuição publicada sem dependência do
  checkout — `pip install <req>` direto. Mutuamente exclusivo com
  `--editable`. O nome do spec é validado por PEP503
  (`canonical_dist_name`): `--dist "outra-coisa==1"` recusa.
- `--allow-url` é opt-in obrigatório para specs `@ https://…` — sem ele
  o bootstrap recusa com código de refusal próprio.
- Credenciais em URL (`user:pass@host`) são removidas por
  `redact_url_userinfo` **antes** de qualquer log/recibo — o spec
  persistido no manifesto nunca carrega segredo.
- `FORGE_PYTHON`/`--python` aceitam invocação com args (`"py -3.11"`);
  um path real com espaços nunca é quebrado.
- O smoke check roda **antes** de registrar launcher/ambiente — um
  pacote que não importa não deixa entrada registrada.
- Recibo: `source.kind` é `pypi` (spec redigido) ou `git-checkout`
  (path/ref/rev/editable); `managed_files` lista exatamente o que foi
  escrito (repair/uninstall leem a mesma lista); `source_trust`
  classifica A/B/C — A exige git+manifesto+estrutura+checksums.
