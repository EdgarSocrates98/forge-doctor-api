# MCP — forge-doctor-api

Servidor MCP: `forge-doctor-api mcp`

A instalação registra uma entrada gerenciada em `.mcp.json` (chave
`_forge_managed.forge-doctor-api`) — outras entradas suas ficam intactas.
O `command` gravado é o argv **resolvido, absoluto** — o shim registrado
pelo bootstrap, ou `python -m forge_doctor_api mcp` — nunca um PATH
lookup (§9.3). O `doctor` audita exatamente esse argv: executável
ausente vira `BLOCKED`, não sucesso fingido.

Verificar de verdade (handshake real + tools/list + invocação segura):

```bash
python scripts/forge_install.py mcp-verify
```

O doctor executa `initialize` → `tools/list` → `tools/call` de leitura
quando o forge declara uma ferramenta de verificação, e reporta PASS /
BLOCKED / FAIL / UNVERIFIED com evidência de processo (exit, stderr).
Nunca infere sucesso de presença de arquivo.
