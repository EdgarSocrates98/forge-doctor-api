# Troubleshooting — forge-doctor-api

| Sintoma | Ação |
|---|---|
| `command not found: forge-doctor-api` | rode `./setup.sh` de novo; abra terminal novo (launcher no PATH) |
| `FORGE-INSTALL-LOCKED` | outra instalação em curso; se foi interrompida, o lock expira/recupera sozinho |
| `FORGE-INSTALL-PLAN-NOT-APPROVED` | mutações exigem `--yes` (após o `--dry-run`) |
| `FORGE-INSTALL-NOT-A-REPO` | escopo project precisa de `.git` ou `--root` |
| doctor FAIL em mcp-handshake | `python scripts/forge_install.py mcp-verify` mostra stderr_tail — geralmente dependência ausente |
| doctor marca `.mcp.json` em drift após upgrade | o argv gerenciado agora é absoluto (shim/`python -m`); `repair` regrava a chave — instalações antigas com `command` no PATH atualizam sozinhas |
| arquivo seu sumiu? | não deveria — instalação nunca sobrescreve conteúdo do usuário; backups em `<state_dir>/backups/` |
| drift detectado | `python scripts/forge_install.py repair` restaura regiões gerenciadas mantendo o resto |
