# Economia de tokens e contexto — Forge Doctor API

## Por que não carregar tudo

Cada skill, agent e tool MCP publicada no host custa contexto de sistema.
35 comandos na surface travada por release-candidate. O MCP expõe tools read-only; instalação e health-check do ciclo de vida rodam pelo `scripts/forge_install.py` para não inflar a surface pública.

## Progressive disclosure

O modelo do ecossistema: o host recebe *índices* (nomes + uma linha), não
o corpo dos documentos. A skill certa é carregada quando a tarefa chega —
`capabilities`/`next-step`/`agents` respondem "o que existe" sem gastar
o que o conteúdo custa.

## O que é medido vs estimado

Recibos de instalação carregam `context`: `skills_bytes`, `agents_bytes`,
`managed_bytes`, `mcp_entries`, `managed_entries`, `tools_exposed` — bytes
observados em disco, não tokens. Estimativas de token são marcadas como
tal; claims de economia percentual exigem baseline do mesmo caso.

## Quando o que usar

| Situação | Caminho mais barato |
|---|---|
| resposta determinística possível | CLI direto (zero modelo) |
| julgamento sobre facts | skill especializada via host |
| investigação multi-etapa | coordinator/playbook |
| catálogo de tools | MCP `tools/list` uma vez, depois `tools/call` |

## Instalação por perfil

`minimal` publica o mínimo de contexto; `recommended` é o padrão
equilibrado; `full` publica tudo — escolha `full` só quando o host vai
usar a superfície inteira, caso contrário é contexto pago sem retorno.
