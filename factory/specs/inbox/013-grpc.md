---
id: 013-grpc
title: gRPC/proto model, compatibility, and reliability checks
agent: claude
risk: high
grill: required
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from §25, §26, §27, §44, §157, §185.
- Problem: proto contracts have strict compatibility semantics (field numbers, reserved) and unique reliability surface (deadlines, streaming).
- Out of scope: protoc codegen, live gRPC calls, server reflection.
- Review failure: field-number reuse missed, unary↔streaming change unclassified, retry finding on non-idempotent method asserted rather than candidate.
- Riskiest assumption: proto parsing approach — OPEN: confirm a hand-rolled `.proto` parser (stdlib, deterministic, offline) vs a parsing dependency; protoc itself is out (execution/network).
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
