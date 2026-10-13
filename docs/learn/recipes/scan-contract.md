# Receita — auditoria determinística completa do serviço

**O quê:** `forge-doctor-api scan <target>` (§177) roda todos os pipelines
determinísticos + o gate §178 opcional.
**Por que:** diagnóstico completo numa passada — contrato, implementação,
segurança, confiabilidade — evidence-first.
**Quando:** auditoria de API, pré-release, baseline de saúde.
**Quando não:** uma pergunta estreita — `contract`, `security`,
`reliability`, `runtime` são os verbos cirúrgicos.

## Passo a passo

```bash
forge-doctor-api scan .                        # console
forge-doctor-api scan . --format json          # máquina
forge-doctor-api scan . --fail-on breaking,security   # gate §178
forge-doctor-api scan . --format report --out report.json
```

## Interpretação

Findings por pipeline com severidade + evidência; `--fail-on` transforma em
gate (categorias: `breaking,security,policy`). `--stats-timing` mede cada
analyzer (não-canônico, fora do relatório determinístico).

## Verificação

`--format report` persiste o `DoctorReport` completo; `diagnose`/`explain`
operam sobre os mesmos findings depois.

## Limitações

Determinístico e offline — `runtime` analisa evidência *exportada*, não
instrumenta produção; `mcp` requer o extra `mcp`.

## Erros comuns

| Sintoma | Causa | Ação |
|---|---|---|
| gate falha com findings | `--fail-on` atingido | leia findings; não remova o gate |
| formato inválido | typo de `--format` | console\|json\|jsonl\|sarif\|agent\|report |

## Uso por agentes

`--format agent` existe para consumo de host; workflow `scan` do
`forge.agentic.json`.
