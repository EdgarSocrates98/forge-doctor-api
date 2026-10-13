# Receita — os findings formam qual sintoma?

**O quê:** `forge-doctor-api diagnose` (§165) agrupa findings em
sintoma/causas candidatas/serviços afetados/desconhecidos; `explain` (§166)
renderiza a cadeia de evidência + rationale da regra.
**Por que:** 40 findings soltos não respondem "o que está doente".
**Quando:** triagem de um `scan` grande, postmortem, priorização.
**Quando não:** inventário — `scan`/`inventory`; blast de mudança —
`blast-radius`.

## Passo a passo

```bash
forge-doctor-api scan . --format json     # produz findings
forge-doctor-api diagnose --help          # entrada do bundle
forge-doctor-api explain <finding>        # evidência + rationale
```

## Interpretação

`diagnose` devolve *sintomas* com causas candidatas e `unknowns` — os
desconhecidos ficam declarados, nunca preenchidos por chute. `explain`
ancora cada finding em regra + evidência.

## Verificação

Cada causa candidata remete a findings do scan original — cadeia
rastreável, não resumo livre.

## Limitações

Diagnose organiza evidência — não inventa causa fora dela; `unknowns` alto
pede mais coleta, não mais inferência.

## Erros comuns

| Sintoma | Causa | Ação |
|---|---|---|
| diagnose sem sintomas | findings insuficientes | rode `scan` completo |
| explain sem evidência | finding de fonte externa | explique só findings do scan |

## Uso por agentes

Formato ideal para brief: sintoma → causas → evidência → unknowns.
