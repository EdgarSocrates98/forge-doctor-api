"""Test fixture: a minimal APPROVED_LOCAL plugin module.

Exposes the `analyze(ctx, files)` run surface the conformance harness
looks for. Deterministic and offline — returns an empty list so the
conformance checks exercise plumbing, not findings.
"""


def analyze(ctx, files):
    return []
