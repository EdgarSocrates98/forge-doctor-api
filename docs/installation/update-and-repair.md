# Update e repair — forge-doctor-api

## Update

```bash
forge-doctor-api update --to <versão ou tag pinada>
```

`latest` é recusado por contrato — sempre pin a versão. Sem checkout
registrado o update reporta BLOCKED honestamente.

## Repair

```bash
forge-doctor-api doctor   # mostra o drift
forge-doctor-api repair   # reassegura regiões gerenciadas
```

Repair restaura arquivos gerenciados removidos e cura blocos
`forge-doctor-api:managed` dentro de arquivos seus — conteúdo fora do bloco nunca
é tocado. Antes de sobrescrever, um snapshot vai para
`<state_dir>/backups/`.
