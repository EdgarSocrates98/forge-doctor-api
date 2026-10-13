"""Operation identity (§181) and conservative path normalization (§182).

Identity:

1. `operationId` when present and non-blank: `operation_id:{operationId}`.
2. Otherwise `method_path:{METHOD} {normalized path}`.

Normalization is deliberately minimal:

- the HTTP method is upper-cased;
- surrounding whitespace is trimmed from the path.

Nothing else changes. In particular, parameter names are kept
(`/users/{id}` and `/users/{userId}` stay distinct), trailing slashes are
kept (`/users/` != `/users`), case is kept, and percent-encoding is not
decoded: those may be equivalent, but merging them without knowing the
semantics would be a weak fuzzy match. `path_shape` exposes the structural
form for callers that want to *flag* similar paths — never to merge them.
"""

from __future__ import annotations

import re

_PARAM = re.compile(r"\{[^{}/]*\}")


def normalize_method(method: str) -> str:
    return method.strip().upper()


def normalize_path(path: str) -> str:
    return path.strip()


def path_shape(path: str) -> str:
    """Path with parameter names erased (`/users/{id}` -> `/users/{}`). Comparison aid only."""
    return _PARAM.sub("{}", normalize_path(path))


def operation_identity(method: str, path: str, operation_id: str | None = None) -> str:
    if isinstance(operation_id, str) and operation_id.strip():
        return f"operation_id:{operation_id.strip()}"
    return f"method_path:{normalize_method(method)} {normalize_path(path)}"
