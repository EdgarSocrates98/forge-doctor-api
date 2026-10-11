"""Portal adapter + entrypoint tests — ``scripts/forge_portal.py``.

Same seam as ``test_forge_install.py``: the entrypoint is driven as a
subprocess (the real operator path), while the adapter module is loaded
via ``importlib`` for in-process unit checks — both live in ``scripts/``
because the package boundary bans network imports in ``src/`` and the RC
window forbids new CLI commands.

Covers: honest NOT_INSTALLED state on a virgin workspace, install plan →
confirm → apply with a real receipt, the session-token gate (403 without
it), named refusals (ambiguous intent, stale plan token, absent host),
the real ``scan_project`` engine task and the vendored-assets refusal.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCRIPT = SCRIPTS / "forge_portal.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pa():
    sys.path.insert(0, str(SCRIPTS))
    try:
        yield _load("forge_portal_adapter", SCRIPTS / "forge_portal_adapter.py")
    finally:
        sys.path.remove(str(SCRIPTS))


@pytest.fixture(scope="module")
def fp(pa):
    return pa.fp


@pytest.fixture()
def target(tmp_path: Path) -> Path:
    root = tmp_path / "consumer"
    root.mkdir()
    (root / ".git").mkdir()
    return root


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("FORGE_HOME_OVERRIDE", str(home))
    return home


def _server(adapter, fp):
    server = fp.PortalServer(adapter, quiet=True)
    server.serve_in_thread()
    return server


def _call(srv, method: str, path: str, body: dict | None = None,
          session: str | None = "USE_TOKEN"):
    req = urllib.request.Request(
        f"http://127.0.0.1:{srv.port}/api/v1{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Forge-Session": srv.session_token if session == "USE_TOKEN" else session or "",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _ctx(server, fp, body: dict):
    handler = type("H", (), {"server": server})()
    return fp.RequestContext(
        handler=handler, body=body, query={}, params={}, correlation_id="t")


# --- descriptor / health -----------------------------------------------------


def test_descriptor_is_real(pa, target: Path) -> None:
    a = pa.ForgeDoctorApiPortal(target)
    d = a.descriptor()
    assert d["forge_id"] == "forge-doctor-api"
    assert d["cli"] == "forge-doctor-api"
    assert any(c["id"] == "scan" and c["state"] == "supported" for c in d["capabilities"])
    assert any(c["id"] == "skills" and c["state"] == "unsupported" for c in d["capabilities"])


def test_health_not_installed_on_virgin_workspace(pa, target: Path) -> None:
    h = pa.ForgeDoctorApiPortal(target).health()
    assert h["state"] == "NOT_INSTALLED"
    assert h["workspace"] == str(target)


# --- http layer: session, plan → apply, refusals ------------------------------


def test_bootstrap_requires_session(pa, fp, target: Path) -> None:
    srv = _server(pa.ForgeDoctorApiPortal(target), fp)
    try:
        code, _doc = _call(srv, "GET", "/bootstrap", session="")
        assert code == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_install_plan_then_apply_roundtrip(pa, fp, target: Path) -> None:
    srv = _server(pa.ForgeDoctorApiPortal(target), fp)
    try:
        code, boot = _call(srv, "GET", "/bootstrap")
        assert code == 200, boot
        code, plan_doc = _call(
            srv, "POST", "/installation/plan",
            {"scope": "project", "host": "devin", "profile": "minimal"})
        assert code == 200, plan_doc
        plan = plan_doc["data"]["plan"]
        token = plan_doc["data"]["plan_token"]
        code, applied = _call(
            srv, "POST", "/installation/apply",
            {"plan": plan, "plan_token": token, "confirm": "apply"})
        assert code == 200, applied
        assert applied["data"]["status"] == "completed"
        code, health = _call(srv, "GET", "/health")
        assert health["data"]["state"] != "NOT_INSTALLED"
    finally:
        srv.shutdown()
        srv.server_close()


def test_apply_rejects_stale_plan_token(pa, fp, target: Path) -> None:
    srv = _server(pa.ForgeDoctorApiPortal(target), fp)
    try:
        code, doc = _call(
            srv, "POST", "/installation/apply",
            {"plan": {"scope": "project"}, "plan_token": "forged", "confirm": "apply"})
        assert code == 409
        assert doc["error"]["code"] == "PORTAL-PLAN-STALE"
    finally:
        srv.shutdown()
        srv.server_close()


def test_spa_served(pa, fp, target: Path) -> None:
    a = pa.ForgeDoctorApiPortal(target)
    assert a.assets_dir is not None
    srv = _server(a, fp)
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{srv.port}/", timeout=30) as r:
            html = r.read().decode()
        assert "<" in html
    finally:
        srv.shutdown()
        srv.server_close()


# --- hosts / mcp ----------------------------------------------------------------


def test_hosts_flow_reports_real_probe(pa, target: Path) -> None:
    hosts = pa.ForgeDoctorApiPortal(target)._hosts()
    assert {h["host"] for h in hosts} == set(pa.forge_hosts.HOST_NAMES)


def test_hosts_launch_refuses_absent_or_copies_command(pa, target: Path) -> None:
    a = pa.ForgeDoctorApiPortal(target)
    doc = a._hosts_launch(type("C", (), {"body": {"host": "copilot"}})())
    if doc.get("refusal") == "PORTAL-HOST-ABSENT":
        assert doc["command"] is None
    else:
        assert isinstance(doc["command"], str)


def test_mcp_verify_named_status(pa, target: Path) -> None:
    doc = pa.ForgeDoctorApiPortal(target)._mcp_verify_doc()
    assert doc["status"] in ("PASS", "FAIL", "HANDSHAKE", "BLOCKED", "NOT_APPLICABLE")


# --- skills / agents: honest unsupported catalog -------------------------------


def test_skills_agents_empty_by_design(pa, target: Path) -> None:
    a = pa.ForgeDoctorApiPortal(target)
    assert a._skills() == []
    assert a._agents() == []


# --- tasks ---------------------------------------------------------------------


def test_tasks_plan_ambiguous_refuses(pa, fp, target: Path) -> None:
    a = pa.ForgeDoctorApiPortal(target)
    srv = _server(a, fp)
    try:
        with pytest.raises(fp.PortalError) as ei:
            a._tasks_plan(_ctx(srv, fp, {"intent": "reformat my disk"}))
        assert ei.value.code == "FDA-PORTAL-AMBIGUOUS"
    finally:
        srv.shutdown()
        srv.server_close()


def test_tasks_mcp_intent_maps_to_verify(pa, fp, target: Path) -> None:
    a = pa.ForgeDoctorApiPortal(target)
    srv = _server(a, fp)
    try:
        doc = a._tasks_plan(_ctx(srv, fp, {"intent": "verificar o handshake mcp"}))
        assert doc["plan"]["verb"] == "mcp_verify"
    finally:
        srv.shutdown()
        srv.server_close()


def test_tasks_scan_executes_real_engine(pa, fp, target: Path) -> None:
    (target / "api.yaml").write_text(
        "openapi: 3.0.3\ninfo: {title: T, version: '1'}\npaths:\n"
        "  /pets:\n    get:\n      operationId: listPets\n"
        "      responses: {'200': {description: ok}}\n",
        encoding="utf-8",
    )
    a = pa.ForgeDoctorApiPortal(target)
    srv = _server(a, fp)
    try:
        plan_doc = a._tasks_plan(_ctx(srv, fp, {"intent": "scan the project"}))
        assert plan_doc["plan"]["verb"] == "scan"
        out = a._tasks_execute(_ctx(
            srv, fp, {"plan": plan_doc["plan"], "plan_token": plan_doc["plan_token"]}))
        assert out["status"] == "completed"
        receipt = out["task"]["receipt"]
        assert receipt["schema_version"] == "1.0"
        assert "summary" in receipt and "findings" in receipt
        assert a._tasks[-1]["verb"] == "scan"
    finally:
        srv.shutdown()
        srv.server_close()


# --- entrypoint: subprocess, the real operator path ------------------------------


def _run_script(*args: str, cwd: Path | None = None, timeout: int = 30):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(cwd) if cwd else None)


def test_entrypoint_help_lists_flags() -> None:
    proc = _run_script("--help")
    assert proc.returncode == 0
    assert "--no-browser" in proc.stdout
    assert "--root" in proc.stdout
    assert "--port" in proc.stdout


def test_entrypoint_serves_and_answers(target: Path) -> None:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--no-browser", "--root", str(target)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    try:
        line = proc.stdout.readline()
        doc = json.loads(line)
        from urllib.parse import parse_qs, urlsplit
        parts = urlsplit(doc["url"])
        token = parse_qs(parts.query)["forge_session"][0]
        port = parts.port
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/", timeout=10) as r:
            assert r.status == 200
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/v1/bootstrap",
            headers={"X-Forge-Session": token})
        with urllib.request.urlopen(req, timeout=30) as r:
            boot = json.loads(r.read())
        assert boot["data"]["descriptor"]["forge_id"] == "forge-doctor-api"
        assert boot["data"]["health"]["state"] == "NOT_INSTALLED"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
