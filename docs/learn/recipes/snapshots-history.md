# Receita — snapshots, diffs e regressões arquiteturais

**O quê:** `snapshot save` grava o estado do projeto em `.forge-doctor/`;
`snapshot list|diff|regressions` consome a série — o "histórico de
relatórios" do Doctor API.
**Por que:** finding novo ≠ dívida antiga; regressão arquitetural só se
prova comparando dois estados reais, não olhando o diff de texto.
**Quando:** antes de cobrar evolução; PRs que movem arquitetura (novos
serviços, novos edges no grafo, operações removidas).
**Quando não:** primeiro contato com o repo — grave um snapshot primeiro.

## Passo a passo

```bash
forge-doctor-api snapshot save --label main      # grava estado rotulado
forge-doctor-api snapshot list                   # snapshots gravados
forge-doctor-api snapshot diff <a> <b>           # delta spec-049 entre estados
forge-doctor-api snapshot regressions <a> <b>    # regressões com evidência
```

## Interpretação

`diff` traz entities adicionadas/removidas e mudança de capabilities;
`regressions` só cita o que tem evidência nos dois estados — sem evidência,
não há claim.

## Verificação

Depois de `save`, `list` mostra o snapshot; `diff` de um snapshot consigo
mesmo é vazio honesto (bom sanity check).

## Limitações

A série vive no repo (`.forge-doctor/`) — clones limpos começam sem
histórico. Delta é estrutural (grafo/contrato), não de métricas de runtime.

## Erros comuns

| Sintoma | Causa | Ação |
|---|---|---|
| "no snapshots" | nunca salvou | `snapshot save --label <nome>` |
| diff vazio surpresa | os dois estados são o mesmo | confirme os ids com `list` |

## Uso por agentes

`get_regressions`/`get_runtime_baseline` (MCP) leem a mesma ideia no eixo
de runtime exportado.
