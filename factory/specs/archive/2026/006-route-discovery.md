---
id: 006-route-discovery
title: Route discovery — framework adapter contract + FastAPI
agent: claude
risk: high
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from §12, §13, §101, §192, §194, §195.
- Problem: implementation discovery — find real API routes in source code to compare against contracts (§225 Phase F).
- Out of scope: Flask/Express/Spring/etc. adapters (§12 order noted; prompt allows partial coverage — FastAPI first per §195), drift engine (007).
- Review failure: framework attributed on a weak marker, routes extracted from comments/strings, missing source locations, missing router-prefix handling.
- Riskiest assumption: static AST extraction covers idiomatic FastAPI — mitigate with adversarial fixtures (decorator-like text in comments, dynamic routes) per §100/§202.
- Smallest acceptable: `FrameworkAdapter` contract + FastAPI adapter emitting `RouteModel`s + graph entities, with attribution gate.

# Context

Phase F (§225). `RouteModel` (§13): framework, service, method, path, handler, auth, middleware, request_schema, response_schema, status_codes, source_location. Every framework adapter must implement the contract in §192: attribution gate, route discovery, auth discovery, schema discovery, source location, adversarial tests. First framework is FastAPI (§195 — Python, OpenAPI-native, typed models, clear routing). Depth first — no shallow multi-framework sprawl (§194). Attribution requires multiple strong markers (§101).

# Acceptance Criteria

- `FrameworkAdapter` protocol/ABC implementing the §192 contract: `attribution gate`, `route discovery`, `auth discovery`, `schema discovery`, `source_location`, and an adversarial test suite hook.
- FastAPI adapter extracts: `APIRouter` prefixes, `@app.get/post/put/delete/patch/...` and `@router.*` decorators, methods, full paths (prefix + route), handler functions, `response_model`, `status_code`, `dependencies` (auth-relevant), Pydantic request/response models where statically resolvable.
- `RouteModel` emitted per §13 with `source_location` (file:line) for every route.
- Routes produce ServiceGraph entities: Service (repo/service being scanned), Endpoint, Operation, plus EXPOSES/IMPLEMENTS edges per §8/§15.
- Attribution gate: FastAPI is only attributed with strong evidence (e.g. `fastapi` import + `FastAPI()`/`APIRouter` instantiation) — decorator-like text in comments or strings yields nothing (§100–§101).
- Dynamic/unknown route construction is recorded as UNKNOWN rather than guessed.
- Tests per §202 including §100 adversarial cases: fake decorators in comments, dynamic route tables, generated-code directories.
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- FastAPI only. Do not scaffold Flask/Express/Spring adapters — future specs.
- Pure static analysis (Python `ast`); never import or execute the target code (§1).
- Auth discovery records *evidence* (dependency names, decorators) — no inference of policy.
- Hermetic: filesystem access via `ProjectContext` (§203).

# Review Notes

- Verify router prefix composition: nested `include_router` chains, prefix in `FastAPI(root_path)` vs decorator.
- Confirm `response_model` vs return-annotation handling — record both, mark which evidence was used.
- Check no finding/entity is emitted for non-attributed files.
