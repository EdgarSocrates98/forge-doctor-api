# Uninstall — forge-doctor-api

```bash
forge-doctor-api uninstall            # remove só arquivos gerenciados
forge-doctor-api uninstall --purge    # + remove o estado local (.forge-doctor-api/install/)
```

O ledger SHA-256 decide ownership: arquivos que você criou ou modificou
depois da instalação ficam no lugar (reportados como `kept`). Diretórios
que esvaziam são podados; os seus permanecem.
