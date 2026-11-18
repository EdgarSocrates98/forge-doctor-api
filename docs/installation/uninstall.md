# Uninstall — forge-doctor-api

Duas rotas equivalentes, mesmo engine e mesmo ledger:

```bash
# Wheel instalado (rota do catálogo forge-cli --native):
forge-doctor-api install uninstall
python -m forge_doctor_api install uninstall        # forma -m equivalente

# Checkout fonte (este repositório):
python scripts/forge_install.py uninstall
```

Flags úteis (as duas rotas aceitam):

```bash
... uninstall --dry-run   # plano somente — escreve nada, mostra o que sairia
... uninstall --purge     # + remove o estado local (.forge-doctor-api/install/)
... uninstall --root DIR  # alvo explícito (default: raiz VCS ou cwd)
```

O ledger SHA-256 decide ownership: arquivos que você criou ou modificou
depois da instalação ficam no lugar (reportados como `kept`). Diretórios
que esvaziam são podados; os seus permanecem.
