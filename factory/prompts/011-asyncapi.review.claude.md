Review Loop Factory spec `011-asyncapi` against current working tree.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\011-asyncapi.md`

        Review stance:
        - Findings first. Focus correctness, regressions, tests, security, maintainability.
        - Compare implementation against acceptance criteria.
        - Run or inspect verification evidence:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`
        - If accepted, say `ACCEPTED`.
        - If not accepted, say `CHANGES_REQUESTED` and list blocking items.
        - Do not move files. Operator or CLI archive step moves accepted specs.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions sourced from §20, §21, §128.
- Problem: event-driven API surfaces need the same evidence discipline as REST.
- Out of scope: broker runtime ingestion, Kafka/AMQP live inspection — documents and static artifacts only.
- Review failure: 2.x vs 3.x conflation, producer/consumer semantics inverted, checks firing on weak markers.
- Riskiest assumption: dual-version (2.x + 3.x) parsing in one model — mitigate with version-aware normalization like spec 004.
- Smallest acceptable: parse AsyncAPI docs → `AsyncApiModel` → PUBLISHES/SUBSCRIBES/PRODUCES edges + ASYNC001–008.
- RESOLVED: equal depth on 2.x and 3.x — §20 requires both. Implementation: version-aware normalization into a single `AsyncApiModel` (3.x send/receive action semantics canonical; 2.x publish/subscribe verbs normalized into it), mirroring spec 004's OAS 3.0/3.1 approach.

# Context

AsyncAPI comes after REST/OpenAPI (§20). `AsyncApiModel` (§20.1): channels, operations, messages, schemas, servers, protocol_bindings, security, correlation_ids. Graph relationships (§20.2): Service–PUBLISHES→Channel, Service–SUBSCRIBES→Channel, Operation–PRODUCES→Message. Support 2.x and 3.x; knowledge includes AsyncAPI 3.1.0 (§20, §128).

# Acceptance Criteria

- Parse AsyncAPI 2.x and 3.x YAML/JSON into `AsyncApiModel` (§20.1 fields).
- Strong-marker detection gate (like §101): `asyncapi:` version key required — `channels:` alone insufficient.
- Graph materialization: Service, AsyncChannel, Message, Operation entities; PUBLISHES/SUBSCRIBES/PRODUCES edges (§20.2, §8.2).
- Checks ASYNC001–008 per §21: channel without message schema; missing correlation id; producer/consumer schema drift; retry without DLQ evidence; unordered processing assumption; incompatible message evolution; missing consumer ownership; operation without delivery semantics — judgment-dependent ones emit candidates with unknowns.
- $ref handling and cycle safety consistent with spec 004's approach.
- Tests per §202 incl. adversarial fixtures.
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- Offline document parsing only; no broker connections (§1).
- Check IDs stable under `ASYNC###` (§218).
- Schema-evolution findings go through the unified compat direction semantics (§121–§123) — don't invent async-specific breaking rules beyond §21.

# Review Notes

- Verify publish/subscribe direction semantics are mapped correctly for 3.x (send/receive actions vs 2.x verbs).
- Confirm ASYNC003 schema drift reuses the schema-compat machinery, not a parallel implementation.
