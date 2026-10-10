# Receita — o que mudou semanticamente no contrato?

**O quê:** `forge-doctor-api diff` (§66) — eventos de mudança tipados entre
duas versões do contrato, com resumo opcional para PR.
**Por que:** breaking change é classificação, não hunk de diff.
**Quando:** versionamento, review de PR, changelog de API.
**Quando não:** diff de código — `scan`/`contract` cobrem implementação.

## Passo a passo

```bash
forge-doctor-api diff old.yaml new.yaml --json --pr   # eventos + resumo §67
forge-doctor-api fingerprint api/openapi.yaml         # fingerprint semântico (§180)
```

`contract` agrupa inspect/diff/check dedicados de contrato.

## Interpretação

Eventos tipados (operation removida, campo required novo, tipo mudou…)
com a evidência — `fingerprint` dá o hash semântico para comparação rápida.

## Verificação

Mesmo par de contratos → mesmos eventos; `fingerprint` igual = semanticamente
equivalente.

## Limitações

Semântica de contrato — compatibilidade de runtime/consumidor real depende
de evidência externa.

## Erros comuns

| Sintoma | Causa | Ação |
|---|---|---|
| eventos inesperados | spec parseada diferente | valide o openapi antes |
| fingerprint difere | mudança semântica real | `diff` mostra o quê |

## Uso por agentes

Eventos tipados são máquina-first — um agente classifica breaking sem
parsear prosa.
