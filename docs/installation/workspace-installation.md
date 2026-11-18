# Instalação em workspace — forge-doctor-api

Monorepo/pasta com vários projetos:

```bash
cd ~/minha-workspace
theforge install auto --scope workspace
# ou membro explícito (repetível):
theforge install auto --scope workspace --member sub/repo
```

Descoberta (installkit 1.0.6): um diretório conta como membro do workspace
quando carrega qualquer marcador — `.git` **ou** um manifesto de projeto
(`forge.json`, `forge.agentic.json`, `pyproject.toml`, `package.json`), então
membros *gitless* são cidadãos de primeira classe. A varredura cobre até 2
níveis de profundidade, nunca segue symlinks/junctions, pula diretórios
ocultos e ignorados (`node_modules`, `.venv`, `dist`, `__pycache__`, …) e
nunca desce dentro de um membro já descoberto — seus submódulos internos
ficam isolados. A raiz explícita (`--root`) também conta quando ela mesma é
uma raiz de projeto.

Cada membro mantém estado e ledger isolados — nenhum runtime duplicado.
Precedência: `project > workspace > user` — instalação local do projeto
vence sempre, e conflitos entre forges são reportados (a via perdedora do
plano consolidado pula o path com nota no receipt), nunca sobrescritos.
