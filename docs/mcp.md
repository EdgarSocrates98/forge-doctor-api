# MCP server

forge-doctor-api serves the Doctor over the Model Context Protocol.
The transport is stdio — fully offline; a socket-blocked environment
still speaks the protocol.

```bash
pip install 'forge-doctor-api[mcp]'
forge-doctor-api mcp services/orders            # stdio
forge-doctor-api mcp services/orders --transport stdio
```

A missing `mcp` extra exits 2 with the install hint.

## Tools

| Tool | Returns |
|---|---|
| `doctor.scan` | full DoctorReport JSON |
| `doctor.inventory` | artifact inventory (classes + counts) |
| `doctor.capabilities` | detected capabilities |
| `doctor.graph` | graph DomainSummary or null |
| `doctor.handoff` | V2 ApiHandoffBundle |
| `doctor.explain` | `{"finding_id": "..."}` → finding + evidence + why |

All tools return compact deterministic JSON text — no payloads, no
raw spans, no schema bodies.

## Resources

| URI | Slice |
|---|---|
| `doctor://service` | ops + finding ids for the service |
| `doctor://graph` | bounded graph projection |
| `doctor://unknowns` | all UnknownFacts |
| `doctor://operation/{op}` | operation + related findings |
| `doctor://finding/{ref}` | one finding + evidence + unknowns |
| `doctor://handoff/{id}` | V2 bundle by handoff id |
