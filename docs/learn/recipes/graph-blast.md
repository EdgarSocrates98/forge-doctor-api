# Receita — grafo de serviços e blast radius

**O quê:** `graph <target>` constrói o grafo de serviços a partir de
contrato + implementação + clientes; `blast-radius <old> <new>` projeta
uma mudança de operação sobre clientes, serviços e fluxos de negócio.
**Por que:** "o que essa mudança quebra?" é a pergunta de toda revisão de
contrato — respondida com cadeia citável, não intuição.
**Quando:** antes de mergear mudança em contrato consumido por clientes;
impacto de deprecar uma operação.
**Quando não:** mudança fora de contrato (runtime) — isso é
`snapshot`/`diagnose`.

## Passo a passo

```bash
forge-doctor-api graph .                  # grafo serviço↔operação↔cliente
forge-doctor-api graph . --json           # máquina
forge-doctor-api blast-radius v1/ v2/     # §68: op -> clientes -> serviços -> fluxos
forge-doctor-api blast-radius v1/ v2/ --clients clients/  # com evidência de clientes
```

## Interpretação

O relatório de blast lista cada operação alterada e os clientes afetados
com evidência (arquivo/símbolo). Sem evidência de cliente, o impacto é
`unknown` — nunca "seguro" por ausência de dados.

## Verificação

`contract diff v1/ v2/ --semantic` emite os mesmos eventos de mudança que
alimentam o blast — compare antes de confiar no raio.

## Limitações

Clientes só entram se houver código-fonte deles (`--clients`) — SDKs
gerados fora do repo não são adivinhados. Correlação estática ≠ chamada
real em produção.

## Erros comuns

| Sintoma | Causa | Ação |
|---|---|---|
| blast vazio | `--clients` ausente | inclua os diretórios de cliente |
| op não encontrada | operationId difere do path | `contract inspect` para ver ids reais |

## Uso por agentes

`get_blast_radius` e `get_breaking_changes` (MCP) servem a mesma análise —
o host cita o relatório sem abrir arquivos.
