You are implementing Loop Factory spec `013-grpc`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\013-grpc.md`
        Spec hash: `dd5c1c0bde7705e9ca466049752cff76aa82aaf8fbfc24bd23e4e1b8e4010ad1`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Claude Code subagents or dynamic workflows only when task is parallel. Prefer project skills in .claude/skills when relevant.

        Required verification:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions sourced from §25, §26, §27, §44, §157, §185.
- Problem: proto contracts have strict compatibility semantics (field numbers, reserved) and unique reliability surface (deadlines, streaming).
- Out of scope: protoc codegen, live gRPC calls, server reflection.
- Review failure: field-number reuse missed, unary↔streaming change unclassified, retry finding on non-idempotent method asserted rather than candidate.
- Riskiest assumption: proto parsing approach — RESOLVED: hand-rolled `.proto` parser (stdlib only, deterministic, offline). protoc is out (execution/network per §1); no parsing dependency exists that covers proto2+proto3 without codegen.
- Smallest acceptable: `.proto` → `GrpcProjectModel`; §26 compat classes; GRPC001–007; deadline/retry/health modeling.

# Context

`GrpcProjectModel` (§25): proto files, packages, services, methods, request/response messages, streaming modes, field numbers, oneof, enums, reserved fields. Compatibility (§26): removed field, field-number reuse, incompatible field-type change, removed enum values, removed method, unary↔streaming change, package/service rename. Reliability (§27): deadline, retry policy, hedging, health check, load balancing, wait-for-ready, keepalive — modeled from service config + proto + generated stub usage (§185). gRPC standard health protocol recognized (§157).

# Acceptance Criteria

- `.proto` parser → `GrpcProjectModel` covering §25 (proto2 and proto3, nested messages, imports of local files — external imports recorded unresolved).
- Graph materialization: GrpcService, GrpcMethod, ProtoMessage entities + EXPOSES/ACCEPTS/RETURNS edges.
- Compatibility rules per §26: each detectable change classified BREAKING/POTENTIALLY_BREAKING/NON_BREAKING/UNKNOWN via the unified engine.
- Field-number bookkeeping: reuse and missing `reserved` after removal detected (GRPC003/004).
- Reliability model from explicit config/proto evidence: deadline propagation awareness (§44), retry policies, hedging, health-check presence, LB, wait-for-ready, keepalive (§27).
- Checks GRPC001–007 per §27: call without deadline evidence; retry on non-idempotent method *candidate*; removed proto field not reserved; field number reused; health service absent from declared production config; incompatible streaming-mode change; retry-policy amplification risk.
- Tests per §202 incl. malformed protos, comment-embedded fake services (§100).
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- GRPC002 stays a *candidate* — idempotency can't be assumed from method shape (§42 spirit).
- No protoc/plugins, no network, no codegen (§1).
- Streaming-mode changes are compat-classified, not just diffed (§26).

# Review Notes

- Verify field-number tracking across proto diffs detects reuse even when names differ.
- Confirm health-check finding (GRPC005) keys on *declared production config* evidence, not just proto absence.
