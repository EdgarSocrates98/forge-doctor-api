"""Workspace tests (spec 024, §108-§109).

Positive: declared members link via evidenced cross-repo edges; the
api -> sdk -> consumer chain resolves; blast radius propagates across
repos. Negative: missing member path, undeclared membership (no
filesystem wandering), ambiguous role, unresolvable subjects -> UNKNOWN.
Boundary: a repo declared twice is handled explicitly, first wins.
"""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.workspace import (
    EdgeKind,
    MemberRole,
    load_workspace,
    scan_workspace,
    workspace_blast_radius,
)

MANIFEST = """name: payments-platform
members:
  - {name: payments-api, path: payments-api, role: service}
  - {name: payments-sdk, path: payments-sdk, role: client, provides: [payments-sdk]}
  - {name: checkout, path: checkout, role: client}
  - {name: gw, path: gw, role: gateway}
"""

API = """openapi: "3.0.3"
info: {title: Payments, version: "1.0"}
paths:
  /charges/{id}:
    get:
      operationId: getCharge
      responses: {'200': {description: ok}}
  /refunds:
    post:
      operationId: refund
      responses: {'200': {description: ok}}
"""

SDK = (
    "import requests\n"
    "def get_charge(cid):\n"
    "    return requests.get('https://api.example.com/v1/charges/' + cid)\n"
    "def fixed():\n"
    "    return requests.get('https://api.example.com/v1/charges/abc')\n"
)
CHECKOUT = "import payments_sdk\nfrom payments_sdk import get_charge\n"
GW_CFG = "routes:\n  - prefix: /charges\n    upstream: payments-api\n"


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _workspace(tmp_path: Path, files: dict[str, str]):
    root = _write(tmp_path / "ws", files)
    ctx = ProjectContext.from_root(root)
    ws = load_workspace(ctx)
    return ctx, ws


def _full(tmp_path: Path):
    return _workspace(tmp_path, {
        "forge-doctor-api.workspace.yaml": MANIFEST,
        "payments-api/api.yaml": API,
        "payments-sdk/sdk.py": SDK,
        "checkout/app.py": CHECKOUT,
        "gw/envoy.yaml": GW_CFG,
    })


# -- manifest -------------------------------------------------------------------


def test_no_manifest_is_not_a_workspace(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, {"payments-api/api.yaml": API})[1]
    assert ws is None
    # and nothing is discovered by wandering
    ctx_scan = ProjectContext.from_root(tmp_path / "ws")
    assert load_workspace(ctx_scan) is None


def test_members_declared_with_roles(tmp_path: Path) -> None:
    ws = _full(tmp_path)[1]
    assert ws is not None and ws.name == "payments-platform"
    roles = {m.name: m.role for m in ws.members}
    assert roles == {
        "payments-api": MemberRole.SERVICE,
        "payments-sdk": MemberRole.CLIENT,
        "checkout": MemberRole.CLIENT,
        "gw": MemberRole.GATEWAY,
    }
    assert not ws.issues


def test_missing_member_recorded_not_invented(tmp_path: Path) -> None:
    ctx, ws = _workspace(tmp_path, {
        "forge-doctor-api.workspace.yaml": MANIFEST,
        # payments-sdk checkout absent
        "payments-api/api.yaml": API,
    })
    assert ws is not None
    missing = {m.name for m in ws.members if not m.present}
    assert "payments-sdk" in missing and "checkout" in missing
    assert any("not found" in i for i in ws.issues)
    scan = scan_workspace(ctx, ws)
    # absent members produce no edges, no crash
    assert not any(
        e.from_repo in missing or e.to_repo in missing for e in scan.edges
    )


def test_duplicate_member_first_wins(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, {
        "forge-doctor-api.workspace.yaml": """members:
  - {name: a, path: a, role: service}
  - {name: a, path: a, role: client}
""",
        "a/api.yaml": API,
    })[1]
    assert ws is not None
    assert len(ws.members) == 1
    assert ws.members[0].role is MemberRole.SERVICE
    assert any("declared twice" in i for i in ws.issues)


def test_missing_role_is_unknown_never_inferred(tmp_path: Path) -> None:
    ctx, ws = _workspace(tmp_path, {
        "forge-doctor-api.workspace.yaml": "members:\n  - {name: x, path: x}\n",
        "x/api.yaml": API,
    })
    assert ws is not None
    assert ws.members[0].role is MemberRole.UNKNOWN
    scan = scan_workspace(ctx, ws)
    assert scan.edges == ()  # UNKNOWN role -> no scans, no edges


def test_member_path_escape_rejected(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, {
        "forge-doctor-api.workspace.yaml":
            "members:\n  - {name: bad, path: ../outside, role: service}\n",
    })[1]
    assert ws is not None and ws.members == ()
    assert any("escapes" in i for i in ws.issues)


# -- §109 cross-repo edges and chains -------------------------------------------


def test_full_chain_edges(tmp_path: Path) -> None:
    ctx, ws = _full(tmp_path)
    scan = scan_workspace(ctx, ws)
    kinds = {(e.kind, e.from_repo, e.to_repo) for e in scan.edges}
    assert (EdgeKind.CLIENT_CALLS, "payments-sdk", "payments-api") in kinds
    assert (EdgeKind.SDK_CONSUMED_BY, "checkout", "payments-sdk") in kinds
    assert (EdgeKind.GATEWAY_ROUTES, "gw", "payments-api") in kinds
    # every edge cites both repos in evidence
    for e in scan.edges:
        assert e.from_repo != e.to_repo
        sources = " ".join(ev.source for ev in e.evidence)
        assert e.from_repo in sources or e.kind is EdgeKind.SDK_CONSUMED_BY


def test_chain_resolution_api_sdk_consumer(tmp_path: Path) -> None:
    ctx, ws = _full(tmp_path)
    scan = scan_workspace(ctx, ws)
    repos = [c.repos for c in scan.chains]
    assert ("checkout", "payments-sdk", "payments-api") in repos
    chain = next(c for c in scan.chains if len(c.repos) == 3)
    assert len(chain.hops) == 2
    assert all(h.evidence for h in chain.hops)


def test_contract_repo_links_implementation(tmp_path: Path) -> None:
    ctx, ws = _workspace(tmp_path, {
        "forge-doctor-api.workspace.yaml": """members:
  - {name: contracts, path: contracts, role: contracts}
  - {name: svc, path: svc, role: service}
""",
        "contracts/payments.yaml": API,
        "svc/api.yaml": API,
    })
    scan = scan_workspace(ctx, ws)
    impl = [e for e in scan.edges if e.kind is EdgeKind.CONTRACT_IMPLEMENTS]
    assert impl and all(e.from_repo == "svc" and e.to_repo == "contracts"
                        for e in impl)
    assert any("charges" in e.subject for e in impl)


def test_gateway_route_without_upstream_is_unknown(tmp_path: Path) -> None:
    ctx, ws = _workspace(tmp_path, {
        "forge-doctor-api.workspace.yaml": """members:
  - {name: gw, path: gw, role: gateway}
  - {name: svc, path: svc, role: service}
""",
        "gw/envoy.yaml": "routes:\n  - prefix: /orphan\n",
        "svc/api.yaml": API,
    })
    scan = scan_workspace(ctx, ws)
    assert any(u.subject == "/orphan" for u in scan.unknowns)
    assert not any(e.kind is EdgeKind.GATEWAY_ROUTES for e in scan.edges)


def test_sdk_import_normalization(tmp_path: Path) -> None:
    """`import payments_sdk` matches declared `payments-sdk`."""
    ctx, ws = _workspace(tmp_path, {
        "forge-doctor-api.workspace.yaml": """members:
  - {name: payments-sdk, path: sdk, role: client, provides: [payments-sdk]}
  - {name: consumer, path: consumer, role: client}
""",
        "sdk/s.py": SDK,
        "consumer/c.py": CHECKOUT,
    })
    scan = scan_workspace(ctx, ws)
    edges = [e for e in scan.edges if e.kind is EdgeKind.SDK_CONSUMED_BY]
    assert len(edges) == 1  # deduped per file
    assert edges[0].from_repo == "consumer" and edges[0].to_repo == "payments-sdk"


def test_no_edges_between_undeclared_repos(tmp_path: Path) -> None:
    """A stray directory beside members is invisible — membership is declared."""
    ctx, ws = _workspace(tmp_path, {
        "forge-doctor-api.workspace.yaml": """members:
  - {name: svc, path: svc, role: service}
""",
        "svc/api.yaml": API,
        "sneaky/client.py": SDK,  # exists on disk but not a member
    })
    scan = scan_workspace(ctx, ws)
    assert all("sneaky" not in e.from_repo + e.to_repo for e in scan.edges)


# -- cross-repo blast radius ----------------------------------------------------


def test_blast_radius_spans_repos(tmp_path: Path) -> None:
    ctx, ws = _full(tmp_path)
    scan = scan_workspace(ctx, ws)
    rep = workspace_blast_radius(scan, ("GET /charges/{id}",))
    node = rep.nodes[0]
    assert node.repo == "payments-api"
    assert set(node.impacted_repos) == {"payments-sdk", "checkout", "gw"}
    # chains show the hop path back to the origin
    assert ("checkout", "payments-sdk") in node.chains


def test_blast_subject_without_consumers_is_unknown(tmp_path: Path) -> None:
    ctx, ws = _workspace(tmp_path, {
        "forge-doctor-api.workspace.yaml": """members:
  - {name: svc, path: svc, role: service}
  - {name: contracts, path: contracts, role: contracts}
""",
        "svc/api.yaml": API,
        "contracts/api.yaml": API,  # implements edges exist but no callers
    })
    scan = scan_workspace(ctx, ws)
    rep = workspace_blast_radius(scan, ("GET /charges/{id}",))
    assert rep.nodes[0].repo == "svc"
    assert rep.nodes[0].impacted_repos == ()
    assert rep.nodes[0].unknowns  # linkage beyond the workspace is UNKNOWN


def test_blast_unresolvable_subject(tmp_path: Path) -> None:
    ctx, ws = _full(tmp_path)
    scan = scan_workspace(ctx, ws)
    rep = workspace_blast_radius(scan, ("DELETE /nothing",))
    assert rep.nodes[0].repo == ""
    assert rep.unknowns


def test_deterministic_scan(tmp_path: Path) -> None:
    ctx, ws = _full(tmp_path)
    a = scan_workspace(ctx, ws)
    b = scan_workspace(ctx, ws)
    assert [(e.kind, e.from_repo, e.to_repo, e.subject) for e in a.edges] == [
        (e.kind, e.from_repo, e.to_repo, e.subject) for e in b.edges
    ]
    assert [c.repos for c in a.chains] == [c.repos for c in b.chains]
