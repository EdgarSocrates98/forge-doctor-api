# Uninstall — forge-doctor-api

```bash
python scripts/forge_install.py uninstall            # remove só arquivos gerenciados
python scripts/forge_install.py uninstall --purge    # + remove o estado local (.forge-doctor-api/install/)
```

O ledger SHA-256 decide ownership: arquivos que você criou ou modificou
depois da instalação ficam no lugar (reportados como `kept`). Diretórios
que esvaziam são podados; os seus permanecem.
