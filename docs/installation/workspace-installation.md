# Instalação em workspace — forge-doctor-api

Monorepo/pasta com vários repositórios:

```bash
cd ~/minha-workspace
theforge install auto --scope workspace
# ou membro explícito (repetível):
theforge install auto --scope workspace --member sub/repo
```

Descoberta: repositórios com `.git` até 2 níveis. Cada membro mantém seu
próprio `.git`, estado e ledger isolados — nenhum runtime duplicado.
Precedência: `project > workspace > user` — instalação local do projeto
vence sempre, e conflitos são reportados, nunca sobrescritos.
