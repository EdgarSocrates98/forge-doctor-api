# Receita — Doctor API vs API Forge: qual usar?

**O quê:** Forge Doctor API **diagnostica** contratos e serviços de API
existentes (evidência, compatibilidade, segurança passiva). API Forge
**projeta e governa** APIs — SDD, spec evolution, host federation.
**Por que:** "está quebrado?" ≠ "como evoluir certo?" — ferramenta errada
responde a pergunta errada.
**Quando:** recebeu um serviço/contrato para revisar → Doctor; vai
projetar/versionar uma API → API Forge.
**Quando não:** os dois se aplicam num ciclo só — diagnostique antes,
governe a mudança depois.

## Passo a passo

| Pergunta | Forja | Verbo inicial |
|---|---|---|
| "o que quebra se eu mudar este contrato?" | Doctor API | `contract diff` / `blast-radius` |
| "esta API vaza dado sensível no contrato?" | Doctor API | `security inspect` |
| "o retry/timeout declarado aguenta?" | Doctor API | `reliability inspect` |
| "como versionar/evoluir esta API?" | API Forge | `apiforge …` |
| "quem consome esta operação?" | Doctor API | `graph` / `get_clients` |

```bash
forge-doctor-api scan .            # diagnóstico completo §177
forge-doctor-api diff v1/ v2/      # diff semântico §66
```

## Interpretação

Doctor emite findings com cadeia de evidência (§166 `explain`); API Forge
emite decisões de design/governança. O Doctor nunca propõe o contrato novo
— ele mede o que existe.

## Verificação

Se a pergunta começa com "está certo/seguro/compatível?", é Doctor.
Se começa com "como faço/evoluo/publico?", é API Forge.

## Limitações

Doctor API não orquestra pipelines nem fala com gateways; evidência de
runtime é importada (`runtime`, `snapshot`).

## Erros comuns

| Sintoma | Causa | Ação |
|---|---|---|
| "quero gerar o contrato" | geração é design-time | API Forge |
| "quero saber se quebra cliente" | diagnóstico estático | Doctor API `blast-radius` |

## Uso por agentes

`the-forge` (hub) roteia "diagnosticar/governar" para a forja certa; o
catálogo MCP do Doctor (`get_*`) serve o host sem trocar de ferramenta.
