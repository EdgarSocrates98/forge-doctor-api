# Tutorial — primeira execução real (forge-doctor-api)

Task-first: do zero ao primeiro resultado em minutos. Todos os exemplos
abaixo são classificados — rode os `offline` sem credencial nenhuma.

## 1. Instalar (offline)

```bash
git clone <forge-doctor-api>
cd forge-doctor-api
./setup.sh        # Windows: .\setup.ps1
```

`setup.sh` cria a venv, constrói o wheel e publica o launcher — sem rede
além do download de dependências Python (uma vez).

## 2. Descobrir (offline)

```bash
forge-doctor-api
```

Sem argumentos o CLI mostra o resumo do produto e os comandos mais usados
— nunca um erro, nunca uma mutação. `forge-doctor-api --help` aprofunda.

## 3. Primeiro comando (offline)

```bash
forge-doctor-api scan .
```

varre o projeto e emite findings.

## 4. Segundo passo (offline)

```bash
forge-doctor-api inventory --help
```

inspeciona os checks disponíveis.

## 5. Instalar nos hosts (mutação confirmada)

```bash
python scripts/forge_install.py install --dry-run     # plano: nada é escrito
python scripts/forge_install.py install --yes         # aplica após aprovar o plano
```

instala a integração (surface travada por RC — a instalação roda pelo script, não por verbos novos na CLI). `--dry-run` antes de `--yes` é o padrão do ecossistema.

## 6. Verificar (offline)

```bash
python scripts/forge_install.py mcp-verify
```

Verificação real: handshake MCP → `tools/list` → `tools/call` segura →
saída limpa do processo. Um `FAIL` aqui vem com `stderr_tail` e
`process.exit_code` — é diagnóstico, não enfeite.

## 7. Próximo passo

```bash
python scripts/forge_install.py doctor
```

verifica saúde do ambiente.

## Classificação dos exemplos

| Exemplo | Classe |
|---|---|
| setup.sh / clone | offline (precisa rede só p/ deps Python) |
| `forge-doctor-api` bare, help, capabilities | offline |
| analyze/scan/judge locais | offline — nunca toca credencial |
| install --dry-run/--yes | offline, mutação no disco local |
| mcp-verify | offline, spawna o servidor MCP local |
| collect */ chamadas de cloud | **credenciais de cloud necessárias** |
| uso via Claude/Devin/Codex | **requer host instalado** |

## Erros comuns

| Sintoma | Causa | Ação |
|---|---|---|
| `command not found: forge-doctor-api` | launcher fora do PATH ou shell velha | abra terminal novo; rode `./setup.sh` de novo |
| `FORGE-INSTALL-LOCKED` | instalação concorrente/interrompida | lock expira e é recuperado sozinho; repita |
| `FORGE-INSTALL-PLAN-NOT-APPROVED` | mutação sem `--yes` | rode `--dry-run`, depois `--yes` |
| MCP `FAIL` com stderr | dependência ausente (ex.: extra `mcp`) | instale o extra e repita `mcp-verify` |

Mais: [../installation/troubleshooting.md](../installation/troubleshooting.md).
