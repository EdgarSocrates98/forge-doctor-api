---
id: cyc9-09
title: scenarios-doctor-api
status: inbox
created: 2026-10-15
owner: forge-doctor-api
scope: repo
cycle: 9
wave: 3
priority: p1
risk: medium
agent: codex
source: prompt_evo_cycles.md §9.3 Doctors
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
  - forge-doctor-api lab
---

# Cenários Forge Lab — Forge Doctor API

## Outcome

Biblioteca versionada de cenários de diagnóstico de APIs com fixtures e diagnósticos previamente classificados, medindo precisão, falsos positivos/negativos, tempo de execução, reprodutibilidade e cobertura das regras.

## Grill gate

- Problema observado: precisão/cobertura das regras do doctor não é medida contra corpus classificado.
- Usuário afetado: Benchmark Engineer; usuário que confia no diagnóstico.
- Falha concreta: falso positivo/negativo sem medição degrada confiança silenciosamente.
- Decisão: corpus de casos com veredito esperado por regra/domínio (OpenAPI, versioning, breaking change, AsyncAPI, políticas, IaC etc.), replay determinístico.
- Fora de escopo: centralizar avaliação no the-forge; cenários exigindo serviços reais.
- Critério de parada: precision/recall/FP por regra publicados com evidência.

## Acceptance

- Fixtures por domínio suportado com expected.yaml (veredito por regra).
- Métricas §9.5 por execução: precision, recall, false_positive_rate, cobertura, tempo, reprodutibilidade.
- Saída compatível com contrato de métricas (cyc9-02); regras não cobertas → `not_available`.
- Ledger de divergências expected-vs-observed.

## Constraints

- Execução local e determinística; sem credenciais.

## Pending

- ⚠ Domínios suportados e formato de fixture atual (baseline cyc0-01).
- ⚠ RC window: `docs/rc-discipline.md` — mudanças de surface/contrato exigem exceção registrada.
- ⚠ `forge-doctor-api lab` já é corpus precision/recall — reutilizar como motor local do lab (alinha com §9.2 "reutilizar existente").
