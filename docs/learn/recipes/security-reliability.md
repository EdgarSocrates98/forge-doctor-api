# Receita — análise passiva de segurança e confiabilidade

**O quê:** `security inspect <target>` avalia o contrato e a configuração
declarada (§163); `reliability inspect` avalia timeouts, retries e
políticas declaradas (§164). Passivo = evidência declarada, nunca probe.
**Por que:** a maior parte dos problemas de API já está escrita no
contrato/config — auth ausente, scope largo, retry sem backoff, timeout
infinito.
**Quando:** pré-release, revisão de contrato, gate de segurança offline.
**Quando não:** pentest, análise de tráfego, prova de exploit — fora de
escopo por desenho (o Doctor nunca toca a rede).

## Passo a passo

```bash
forge-doctor-api security inspect .          # findings de segurança passivos
forge-doctor-api security inspect . --json
forge-doctor-api reliability inspect .       # timeouts/retries declarados
forge-doctor-api reliability path . --hop a --hop b   # confiabilidade num call path
```

## Interpretação

Findings citam a evidência no contrato/config (operationId, securityScheme,
timeout declarado). `unknowns` explícitos quando a evidência não existe —
`Confidence.UNKNOWN` nunca vira "ok".

## Verificação

`scan . --fail-on security` transforma a inspeção em gate — reprova o
build quando a categoria dispara.

## Limitações

Passivo: não valida que o servidor aplica a política — só que ela está
(ou não está) declarada. Sem credenciais, sem enumeração.

## Erros comuns

| Sintoma | Causa | Ação |
|---|---|---|
| "no security findings" enganoso | esquema ausente ≠ seguro | veja `unknowns` no relatório |
| reliability vazio | config não declarada no repo | exporte a config ou declare-a |

## Uso por agentes

`get_security_findings` e `get_reliability_status` (MCP) devolvem o mesmo
modelo — findings navegáveis por `explain`.
