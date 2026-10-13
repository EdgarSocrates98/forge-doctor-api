"""§136/§215 Forger routing contract — structured I/O, never execution.

`route_request` maps a `ForgerRequest` to a `ForgerRoute`: `domain=api`
routes Doctor API output toward API Forge; an external reference pointing
to a data-owned entity routes to the Data Doctor (Spark Forge when the
task implies implementation). The Doctor declares routes — The Forger
executes them.
"""

from __future__ import annotations

from forge_doctor_api.core.models import UnknownFact
from forge_doctor_api.handoff.model import (
    ExternalReference,
    ForgerRequest,
    ForgerRoute,
)

_DOMAIN_HANDLERS = {
    "api": "api-forge",
    "data": "data-doctor",
}

# §215: API dependency pointing at a data path routes to Data Doctor;
# implementation-grade data work continues to Spark Forge.
_DATA_IMPLEMENT_HINTS = ("migration", "schema change", "backfill",
                         "transform", "implement", "build")


def route_request(
    request: ForgerRequest,
    references: tuple[ExternalReference, ...] = (),
) -> ForgerRoute:
    if request.domain == "api":
        data_refs = tuple(
            r for r in references
            if r.target_domain.replace("_", "-").startswith("data")
        )
        if data_refs:
            impl = any(h in request.task.lower()
                       for h in _DATA_IMPLEMENT_HINTS)
            chain = ["doctor-api", "data-doctor"]
            if impl:
                chain.append("spark-forge")
            return ForgerRoute(
                domain="api",
                handler="data-doctor",
                reason=(
                    "API dependency evidence points to a data-owned "
                    "entity"
                    + (" and the task implies implementation work"
                       if impl else "")
                ),
                chain=tuple(chain),
                references=data_refs,
            )
        return ForgerRoute(
            domain="api",
            handler="api-forge",
            reason="domain=api routes Doctor API output to API Forge",
            chain=("doctor-api", "api-forge"),
            references=references,
        )
    handler = _DOMAIN_HANDLERS.get(request.domain)
    if handler is not None:
        return ForgerRoute(
            domain=request.domain,
            handler=handler,
            reason=f"declared domain routes to {handler}",
            chain=(f"doctor-{request.domain}", handler),
            references=references,
        )
    return ForgerRoute(
        domain=request.domain,
        handler="unrouted",
        reason="no declared route for this domain",
        references=references,
        unknowns=(UnknownFact(
            subject=request.domain,
            missing="routing rule for domain",
            resolution="declare a domain->handler mapping in the routing "
                       "contract",
        ),),
    )
