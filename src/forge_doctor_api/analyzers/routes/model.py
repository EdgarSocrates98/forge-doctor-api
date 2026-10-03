"""`RouteModel` (§13) — one implemented API route found in source code.

Pure static-analysis output: every field is evidence extracted from the AST.
When route construction is dynamic, the route is skipped and the site is
recorded in `RouteScan.unknowns` instead of being guessed (§101).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import (
    Evidence,
    Model,
    SourceLocation,
    UnknownFact,
)


class ResponseSchemaSource(StrEnum):
    """Which evidence supplied `RouteModel.response_schema` (§192)."""

    RESPONSE_MODEL = "RESPONSE_MODEL"
    RETURN_ANNOTATION = "RETURN_ANNOTATION"


@dataclass(frozen=True, kw_only=True)
class RouteParam(Model):
    """One handler parameter as static evidence.

    `location_in` mirrors the OpenAPI vocabulary (`path`, `query`, `header`,
    `cookie`, `body`) plus `dependency` for `Depends`/`Security` params.
    `required` is True only when the parameter has no default.
    """

    name: str
    location_in: str
    required: bool = False
    annotation: str | None = None


@dataclass(frozen=True, kw_only=True)
class RouteModel(Model):
    """One implemented route.

    - `framework`: adapter name (e.g. `fastapi`).
    - `service`: service identity the adapter was scoped to.
    - `method`/`path`: HTTP method + full path (router prefixes composed).
    - `handler`: qualified function name (`module.function`).
    - `auth`: names wrapped in `Security(...)` — evidence, not policy.
    - `middleware`: names from `dependencies=[Depends(...)]` and
      `add_middleware(...)` calls that apply to the route.
    - `request_schema`: name of the annotated body model, when statically
      resolvable.
    - `response_schema`: `response_model=` or return annotation;
      `response_schema_source` says which.
    - `status_codes`: declared statuses (`status_code=` kwarg); empty means
      framework default (recorded in `unknowns` when the value is dynamic).
    """

    framework: str
    service: str
    method: str
    path: str
    handler: str
    auth: tuple[str, ...] = ()
    middleware: tuple[str, ...] = ()
    parameters: tuple[RouteParam, ...] = ()
    request_schema: str | None = None
    response_schema: str | None = None
    response_schema_source: ResponseSchemaSource | None = None
    status_codes: tuple[str, ...] = ()
    source_location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class Attribution(Model):
    """Positive framework attribution for one file (§101: strong markers)."""

    framework: str
    path: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True, kw_only=True)
class RouteScan(Model):
    """Result of scanning a project's source files with one adapter."""

    service: str
    routes: tuple[RouteModel, ...] = ()
    attributions: tuple[Attribution, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
