# Receita — inspecionar um contrato OpenAPI

**O quê:** `forge-doctor-api contract inspect <target>` resolve um
contrato OpenAPI (ou diretório de contratos) em modelo inspecionável:
documentos, operações, schemas, servers, refs.
**Por que:** antes de julgar compatibilidade ou segurança, você precisa do
contrato *resolvido* — refs incluídas, não o texto cru do YAML.
**Quando:** revisar um openapi.yaml novo, auditar superfície publicada,
entender o que um serviço expõe.
**Quando não:** implementação (rotas) — isso é `inventory`/`scan`.

## Passo a passo

```bash
forge-doctor-api contract inspect .               # descobre o contrato no dir
forge-doctor-api contract inspect api/openapi.yaml
forge-doctor-api contract inspect . --json        # modelo resolvido, máquina
forge-doctor-api contract compatibility old/ new/ # §160: classe de cada mudança
```

## Interpretação

Operações com `operationId`, schemas referenciados, servers declarados.
Refs não resolvíveis aparecem como lacuna explícita — nunca silenciadas.

## Verificação

`fingerprint <target>` imprime o fingerprint semântico do contrato — o mesmo
contrato produz o mesmo fingerprint em qualquer máquina (determinismo).

## Limitações

OpenAPI 3.x + AsyncAPI; GraphQL via extra `graphql`. Contratos que só
existem anotados em código entram pelo pipeline de rotas (`scan`), não por
`contract inspect`.

## Erros comuns

| Sintoma | Causa | Ação |
|---|---|---|
| "contract not found" | arquivo fora dos nomes conhecidos | aponte o arquivo direto |
| refs vazias | `$ref` externa a arquivo ausente | inclua o arquivo referenciado |

## Uso por agentes

O modelo resolvido é o que `get_contract`/`get_api` servem via MCP —
mesma verdade, duas superfícies.
