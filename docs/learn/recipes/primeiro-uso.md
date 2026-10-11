# Receita — primeiro uso do Doctor API

**O quê:** `forge-doctor-api` num repo com `openapi.yaml`/`*.py` FastAPI
produz um diagnóstico determinístico sem instalar nem configurar nada.
**Por que:** a primeira pergunta de qualquer repo de API é "o que está
declarado e o que já está quebrando" — resposta em um comando.
**Quando:** clone de um serviço novo, onboarding, pré-review.
**Quando não:** repo sem contrato/implementação de API — o Doctor reporta
evidência ausente honestamente, não inventa findings.

## Passo a passo

```bash
pipx install forge-doctor-api              # ou pip install forge-doctor-api
cd meu-servico                             # repo com openapi.yaml ou rotas
forge-doctor-api scan .                    # §177: todos os pipelines
forge-doctor-api inventory .               # serviços, APIs, operações
forge-doctor-api                           # sem args num TTY: menu (TUI)
```

## Interpretação

Findings com severidade + `CHECK-ID` + evidência citável em arquivo.
`inventory` é o mapa — o que o Doctor *viu* antes de julgar.

## Verificação

`forge-doctor-api explain . <finding>` mostra a cadeia de evidência e o
rationale da regra — findings nunca são opinião solta.

## Limitações

Análise estática: não chama a API, não mede latência real; `runtime`
analisa evidência exportada (§162).

## Erros comuns

| Sintoma | Causa | Ação |
|---|---|---|
| scan vazio | nenhum contrato/rota detectável | `inventory .` mostra o que foi visto |
| findings demais | repo misto (vários serviços) | aponte `scan` no subdir do serviço |

## Uso por agentes

`--format agent` emite o bundle compacto para hosts; workflows em
`forge.agentic.json`.
