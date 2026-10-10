# Quickstart — forge-doctor-api

Três comandos:

```bash
git clone <forge-doctor-api repo>
cd forge-doctor-api
./setup.sh        # Windows: .\setup.ps1
```

Depois, dentro de qualquer projeto:

```bash
cd ~/meu-projeto
python <forge-doctor-api checkout>/scripts/forge_install.py install --yes --root .
# ou deixe o orquestrador decidir: theforge install auto
```

Pronto. Abra seu AI host (Devin, Claude, Codex ou Copilot) — as skills do
forge-doctor-api já estão instaladas.

## Verificar

```bash
python scripts/forge_install.py status
python scripts/forge_install.py doctor
```

Problemas? → [troubleshooting.md](troubleshooting.md)
