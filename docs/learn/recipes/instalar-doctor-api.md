# Receita — instalar o Doctor API num projeto

**O quê:** `python scripts/forge_install.py` é o adapter de instalação
portátil (contrato `forge/*` v1): chave MCP gerenciada em `.mcp.json`,
marcadores AGENTS.md/CLAUDE.md, ledger em `.forge-doctor-api/`.
**Por que:** instalação governada — plano antes de escrever, drift
auditável, uninstall que só remove o que o ledger criou.
**Quando:** primeira vez num repo, ou para dar ao host de IA o servidor
MCP do Doctor.
**Quando não:** scan rápido — o CLI funciona sem instalar nada.

## Passo a passo

```bash
python scripts/forge_install.py install --dry-run   # plano, sem escrever
python scripts/forge_install.py install --yes       # aplica no projeto
python scripts/forge_install.py status              # saúde/drift
python scripts/forge_install.py doctor              # checks de saúde
python scripts/forge_install.py repair              # restaura o que faltar
python scripts/forge_install.py uninstall           # remove só o ledger
python scripts/forge_install.py mcp-verify          # handshake real do MCP
```

## Interpretação

`status` retorna `healthy|degraded|broken|unverified` com drift por
arquivo. `unverified` = nunca instalado — estado honesto, não erro.

## Verificação

`mcp-verify` faz handshake JSON-RPC real com `forge-doctor-api mcp` —
"configurado" ≠ "verificado".

## Limitações

O adapter é um *script* de checkout, não um verbo do pacote: o boundary
(AST purity) proíbe `subprocess`/`os` em `src/` — efeitos de instalação
ficam fora do engine, por desenho. Escopo `user` grava em `~/.forge/`.
No codex-cli, a chave `.mcp.json` do projeto não é lida pelo host
(limitação do codex 0.160.x) — use `--scope user` ou `codex mcp add`.

## Erros comuns

| Sintoma | Causa | Ação |
|---|---|---|
| `FORGE-INSTALL-NOT-A-REPO` | fora de repo git | `git init` ou `--root` num repo |
| `FORGE-INSTALL-PLAN-NOT-APPROVED` | faltou `--yes` | revise o dry-run, depois `--yes` |
| drift `modified` | arquivo gerenciado editado à mão | `repair` (preserva conteúdo seu) |

## Uso por agentes

O TUI expõe install status + mcp-verify via sentinelas de script; hosts
leem `.mcp.json` na raiz do projeto.
