"""Portal adapter for Forge Doctor API (see ``forge_portal.py``).

Maps forge/PortalApi/1 operations onto the real checkout-level services:
``forge_installkit`` (install lifecycle — the same engine
``scripts/forge_install.py`` drives), ``forge_hosts`` (host probes) and
the ``forge_doctor_api`` package (``scan_project`` / ``graphview`` for
read-only engine runs). Nothing here fabricates state: every field
comes from a real service call; unverifiable values stay ``unverified``.

Lives in ``scripts/`` — NOT ``src/`` — because the package boundary
(``tests/test_boundary.py``) bans ``os``/``subprocess``/network imports
package-wide, and the 0.2.0 RC window forbids new public-surface CLI
commands. Same portal, same contract, same controls as the in-package
adapters shipped by sibling forges; only the entrypoint differs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _forge_portal as fp  # noqa: E402
import _portal_telemetry as _pt  # noqa: E402
import forge_hosts  # noqa: E402
import forge_install  # noqa: E402 — reuse _spec/_ctx/_hosts, never re-implement
import forge_installkit as kit  # noqa: E402

_REPO_ROOT = _SCRIPTS.parent
_ASSETS_CANDIDATES = (_REPO_ROOT / "portal" / "assets",)
_ASSETS_DIR = next((d for d in _ASSETS_CANDIDATES if (d / "index.html").is_file()), None)
_INVENTORY = _REPO_ROOT / "docs" / "knowledge-program" / "inventory.jsonl"
_HOSTS: tuple[str, ...] = forge_hosts.HOST_NAMES
_PROFILES = forge_install.PROFILES
_SCOPES = forge_install.SCOPES


def _ctx_args(
    scope: str,
    root: Path,
    profile: str = "recommended",
    *,
    dry_run: bool = True,
    components: str | None = None,
) -> SimpleNamespace:
    """argparse-shaped namespace for ``forge_install._ctx``."""
    return SimpleNamespace(
        scope=scope,
        root=str(root),
        profile=profile,
        dry_run=dry_run,
        components=components,
    )


def _health_state(status: dict[str, Any], doctor: dict[str, Any] | None) -> str:
    """Map the real lifecycle vocabulary — healthy|degraded|unverified —
    onto the contract InstallState. `status` is the ledger truth: an
    unverified ledger means "never installed", even when `doctor` reports
    `degraded` (its checks fail on missing artifacts)."""
    ledger = str(status.get("status") or "unverified").lower()
    if ledger == "unverified":
        return "NOT_INSTALLED"
    st = str((doctor or status).get("status") or "unverified").lower()
    if st == "unverified":
        return "NOT_INSTALLED"
    if st in ("degraded", "broken"):
        return "DEGRADED"
    if st == "healthy":
        checks = {c.get("id"): c.get("status") for c in (doctor or {}).get("checks", [])}
        mcp = checks.get("mcp-handshake")
        if mcp == "PASS":
            return "VERIFIED"
        if mcp in ("UNVERIFIED", "NOT_APPLICABLE", "BLOCKED"):
            return "ACTIVE"
        return "INSTALLED"
    return "NOT_INSTALLED"


class ForgeDoctorApiPortal(fp.PortalAdapter):
    forge_id = forge_install.FORGE_ID
    forge_name = "Forge Doctor API"
    forge_version = forge_install._VERSION
    cli = "forge-doctor-api"
    theme = "forge-doctor-api"
    federated = False

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = str((workspace or Path.cwd()).resolve())
        self._root = Path(self.workspace)
        self.assets_dir = _ASSETS_DIR
        self._tasks: list[dict[str, Any]] = []
        self._task_seq = 0
        self._telemetry_recorder = _pt.EventRecorder()
        self.event_sink = self._telemetry_recorder.emit
        self.ops = [
            *fp.default_operations(self),
            *_pt.operations(self._telemetry_recorder, self),
            fp.Operation("GET", "/profiles", lambda ctx: self._profiles()),
            fp.Operation("GET", "/hosts", lambda ctx: self._hosts()),
            fp.Operation("GET", "/mcp/servers", lambda ctx: self._mcp_servers()),
            fp.Operation("GET", "/skills", lambda ctx: self._skills()),
            fp.Operation("GET", "/agents", lambda ctx: self._agents()),
            fp.Operation("GET", "/tasks", lambda ctx: list(self._tasks)),
            _pt.task_events_op(self._telemetry_recorder, lambda: list(self._tasks)),
            fp.Operation("GET", "/graphs", lambda ctx: self._graphs()),
            fp.Operation("GET", "/docs/search", lambda ctx: self._docs_search(ctx)),
            fp.Operation("POST", "/installation/plan", self._install_plan, mutating=True),
            fp.Operation(
                "POST", "/installation/apply", self._install_apply,
                mutating=True, confirm="apply", needs_plan_token=True,
            ),
            fp.Operation(
                "POST", "/installation/repair", self._install_repair,
                mutating=True, confirm="repair",
            ),
            fp.Operation(
                "POST", "/installation/uninstall", self._install_uninstall,
                mutating=True, confirm="uninstall",
            ),
            fp.Operation(
                "POST", "/profiles/apply", self._profiles_apply,
                mutating=True, confirm="apply",
            ),
            fp.Operation("POST", "/hosts/launch", self._hosts_launch, mutating=False),
            fp.Operation("POST", "/mcp/verify", self._mcp_verify, mutating=True, confirm="verify"),
            fp.Operation("POST", "/tasks/plan", self._tasks_plan, mutating=True),
            fp.Operation(
                "POST", "/tasks/execute", self._tasks_execute,
                mutating=True, confirm="execute", needs_plan_token=True, timeout=180,
            ),
        ]

    # ------------------------------------------------------------------
    # descriptor / health / capabilities
    # ------------------------------------------------------------------
    def capabilities(self) -> list[dict[str, Any]]:
        return [
            {"id": "install", "state": "supported"},
            {"id": "hosts", "state": "supported"},
            {"id": "mcp", "state": "supported"},
            # this forge ships no repo-authored host assets — honest empty
            {"id": "skills", "state": "unsupported"},
            {"id": "agents", "state": "unsupported"},
            {"id": "tasks", "state": "supported"},
            {"id": "scan", "state": "supported"},
            {"id": "docs", "state": "supported" if _INVENTORY.is_file() else "unverified"},
            {
                "id": "graph",
                "state": "supported" if self._graph_view() is not None else "unverified",
            },
        ]

    def nav(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "tasks",
                "label_key": "nav.tasks",
                "route": "/tasks",
                "requires_capability": "tasks",
            },
            {
                "id": "graph",
                "label_key": "nav.graph",
                "route": "/graph",
                "requires_capability": "graph",
            },
        ]

    def health(self) -> dict[str, Any]:
        status = self._status_doc()
        doctor = None
        doctor_error: str | None = None
        try:
            ctx = forge_install._ctx(_ctx_args("project", self._root), ())
            doctor = kit.doctor(ctx)
        except Exception as e:
            doctor_error = f"{type(e).__name__}: {e}"
        checks = []
        for c in (doctor or {}).get("checks", []):
            checks.append({
                "id": c.get("id", "check"),
                "state": c.get("status", "UNVERIFIED"),
                "detail": c.get("detail"),
            })
        if doctor_error:
            checks.append({"id": "doctor", "state": "UNVERIFIED", "detail": doctor_error})
        return {
            "state": _health_state(status, doctor),
            "checks": checks,
            "workspace": self.workspace,
            "profile": status.get("profile") if status.get("profile") else None,
            "updated_at": status.get("checked_at"),
        }

    def installation_status(self, ctx: fp.RequestContext | None = None) -> dict[str, Any]:
        return self.health()

    def _status_doc(self) -> dict[str, Any]:
        try:
            ctx = forge_install._ctx(_ctx_args("project", self._root), ())
            return kit.status(ctx)
        except Exception:
            return {"drift": {}, "status": "unverified"}

    # ------------------------------------------------------------------
    # installation lifecycle — plan → confirm → apply, real receipts
    # ------------------------------------------------------------------
    def _install_plan(self, ctx: fp.RequestContext) -> dict[str, Any]:
        scope = (ctx.body or {}).get("scope", "project")
        if scope not in _SCOPES:
            raise fp.PortalError(
                "PORTAL-BAD-FIELD", f"scope must be one of {_SCOPES}",
                details={"field": "scope", "got": scope},
            )
        host = (ctx.body or {}).get("host", "all")
        known = (*forge_install.HOSTS, "all", "none")
        if host not in known and not all(
            h.strip() in forge_install.HOSTS for h in str(host).split(",")
        ):
            raise fp.PortalError(
                "PORTAL-BAD-FIELD", f"host must be one of {known}",
                details={"field": "host", "got": host},
            )
        profile = (ctx.body or {}).get("profile", "recommended")
        if profile not in _PROFILES:
            raise fp.PortalError(
                "PORTAL-BAD-FIELD", f"profile must be one of {_PROFILES}",
                details={"field": "profile", "got": profile},
            )
        plan_input = {"scope": scope, "profile": profile, "host": host}
        ictx = forge_install._ctx(
            _ctx_args(scope, self._root, profile), forge_install._hosts(host))
        with kit.acquire_lock(ictx.state_dir):
            receipt = kit.apply_install(ictx, approved=False)
        return {
            "status": receipt.get("status", "planned"),
            "plan": plan_input,
            "plan_token": ctx.handler.server.sign_plan(plan_input),
            "receipt": receipt,
            "actions": [
                {"kind": "file", "path": p, "status": "planned"}
                for p in receipt.get("planned_files", [])
            ],
        }

    def _install_apply(self, ctx: fp.RequestContext) -> dict[str, Any]:
        plan = (ctx.body or {}).get("plan") or {}
        if not ctx.handler.server.check_plan((ctx.body or {})["plan_token"], plan):
            raise fp.PortalError(
                "PORTAL-PLAN-STALE",
                "plan token does not match this plan or expired — regenerate the plan",
                http=409, retryable=True, action="regenerate_plan",
            )
        ictx = forge_install._ctx(
            _ctx_args(
                plan.get("scope", "project"), self._root,
                plan.get("profile", "recommended"), dry_run=False),
            forge_install._hosts(plan.get("host", "all")))
        # same orchestration as forge_install.cmd_install: lock → apply →
        # receipt → registry
        with kit.acquire_lock(ictx.state_dir):
            receipt = kit.apply_install(ictx, approved=True)
        if receipt.get("status") == "completed":
            kit._write_receipt(ictx.state_dir, receipt)
            forge_install._register(ictx)
        return receipt

    def _install_repair(self, ctx: fp.RequestContext) -> dict[str, Any]:
        ictx = forge_install._ctx(
            _ctx_args("project", self._root, "full"), forge_install.HOSTS)
        with kit.acquire_lock(ictx.state_dir):
            return kit.repair(ictx)

    def _install_uninstall(self, ctx: fp.RequestContext) -> dict[str, Any]:
        ictx = forge_install._ctx(_ctx_args("project", self._root), ())
        with kit.acquire_lock(ictx.state_dir):
            return kit.uninstall(ictx, purge_state=False)

    # ------------------------------------------------------------------
    # profiles — portal presets map onto the real install profiles
    # ------------------------------------------------------------------
    def _profiles(self) -> list[dict[str, Any]]:
        current = self._installed_profile()
        return [
            {
                "id": "economy",
                "label_key": "profiles.economy",
                "description_key": "profiles.economy.desc",
                "current": current == "minimal",
                "components": {
                    "skills": False, "agents": False, "mcp": True,
                    "tui": False, "graph_studio": False,
                },
            },
            {
                "id": "balanced",
                "label_key": "profiles.balanced",
                "description_key": "profiles.balanced.desc",
                "current": current == "recommended",
                "components": {
                    "skills": True, "agents": False, "mcp": True,
                    "tui": False, "graph_studio": False,
                },
            },
            {
                "id": "full",
                "label_key": "profiles.full",
                "description_key": "profiles.full.desc",
                "current": current == "full",
                "components": {
                    "skills": True, "agents": True, "mcp": True,
                    "tui": False, "graph_studio": True,
                },
            },
        ]

    def _installed_profile(self) -> str:
        comp = self._root / forge_install.STATE_DIR / "components.json"
        if not comp.is_file():
            return ""
        try:
            doc = json.loads(comp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        if not isinstance(doc, dict) or not doc:
            return ""
        selected = {k for k, v in doc.items() if v}
        if "agents" in selected:
            return "full"
        if "skills" in selected:
            return "recommended"
        return "minimal" if "mcp" in selected else ""

    def _profiles_apply(self, ctx: fp.RequestContext) -> dict[str, Any]:
        profile = (ctx.body or {}).get("profile", "balanced")
        real = {"economy": "minimal", "balanced": "recommended", "full": "full"}.get(profile)
        if real is None:
            raise fp.PortalError(
                "PORTAL-BAD-FIELD",
                f"profile must be one of {(*_PROFILES, 'economy', 'balanced')}",
                details={"field": "profile", "got": profile},
            )
        ictx = forge_install._ctx(
            _ctx_args("project", self._root, real, dry_run=False),
            forge_install._hosts("all"))
        with kit.acquire_lock(ictx.state_dir):
            receipt = kit.apply_install(ictx, approved=True)
        if receipt.get("status") == "completed":
            kit._write_receipt(ictx.state_dir, receipt)
            forge_install._register(ictx)
        return receipt

    # ------------------------------------------------------------------
    # hosts — observe-only via forge_hosts; launch returns the command
    # ------------------------------------------------------------------
    def _hosts(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name in _HOSTS:
            try:
                h = forge_hosts.host_state(name, self._root)
            except Exception as e:
                out.append({
                    "host": name, "detected": False, "version": None,
                    "supported": False, "logged_in": None,
                    "integration": "unverified", "launchable": False,
                    "detail": f"probe failed: {type(e).__name__}",
                })
                continue
            integration = h.get("integration") or {}
            detected = h.get("binary_path") is not None
            out.append({
                "host": h.get("host", name),
                "detected": detected,
                "version": h.get("version"),
                "supported": h.get("state") in ("READY", "SUPPORTED"),
                "logged_in": h.get("logged_in"),
                "integration": integration.get("state", "unverified"),
                "launchable": detected,
                "command_hint": h.get("launch_command") if detected else None,
                "detail": h.get("detail") or h.get("login_hint") or h.get("auth_note"),
            })
        return out

    def _hosts_launch(self, ctx: fp.RequestContext) -> dict[str, Any]:
        host = (ctx.body or {}).get("host")
        if host not in _HOSTS:
            raise fp.PortalError(
                "PORTAL-BAD-FIELD", f"host must be one of {_HOSTS}",
                details={"field": "host", "got": host},
            )
        state = forge_hosts.host_state(host, self._root)
        if state.get("binary_path") is None:
            return {
                "command": None,
                "refusal": "PORTAL-HOST-ABSENT",
                "detail": f"{host} not detected on this system",
            }
        # A portal has no real TTY — return the command to copy.
        return {
            "command": state.get("launch_command"),
            "detail": f"run `{state.get('launch_command')}` in your terminal to open {host}",
            "host": state.get("host"),
        }

    # ------------------------------------------------------------------
    # mcp
    # ------------------------------------------------------------------
    def _mcp_verify_doc(self) -> dict[str, Any]:
        try:
            return kit.mcp_verify(forge_install._spec())
        except Exception as e:
            return {
                "status": "FAIL",
                "detail": f"mcp verify failed: {type(e).__name__}",
            }

    def _mcp_servers(self) -> list[dict[str, Any]]:
        doc = self._mcp_verify_doc()
        status = doc.get("status", "FAIL")
        state = {
            "PASS": "INVOCATION_VERIFIED",
            "HANDSHAKE": "HANDSHAKE_VERIFIED",
            "FAIL": "FAILED",
            "BLOCKED": "DEGRADED",
            "NOT_APPLICABLE": "DEGRADED",
        }.get(status, "DEGRADED")
        return [{
            "id": "forge-doctor-api",
            "state": state,
            "host": None,
            "tools_count": None,
            "last_verify": None,
            "detail": doc.get("detail"),
        }]

    def _mcp_verify(self, ctx: fp.RequestContext) -> dict[str, Any]:
        doc = self._mcp_verify_doc()
        return {
            "status": doc.get("status", "FAIL"),
            "detail": doc.get("detail"),
            "actions": [
                {
                    "kind": "handshake",
                    "path": "mcp://forge-doctor-api",
                    "status": doc.get("status", "FAIL"),
                }
            ],
        }

    # ------------------------------------------------------------------
    # skills / agents — this forge ships no host-asset catalog today.
    # ------------------------------------------------------------------
    def _skills(self) -> list[dict[str, Any]]:
        return []

    def _agents(self) -> list[dict[str, Any]]:
        return []

    # ------------------------------------------------------------------
    # tasks — safe read-only diagnostics mapped from intent, real receipts
    # ------------------------------------------------------------------
    _SAFE_TASKS: tuple[tuple[tuple[str, ...], str, str], ...] = (
        (("mcp", "handshake"), "mcp_verify", "MCP handshake verification"),
        (("doctor", "saúde", "saude", "verifica", "verif"), "doctor", "installation doctor"),
        (("scan", "diag", "analis", "findings"), "scan", "project diagnostics scan"),
        (("grafo", "graph"), "graph", "graph summary"),
        (("status", "estado", "instala"), "status", "installation status"),
    )

    def _intent_to_task(self, intent: str) -> tuple[str, str] | None:
        low = intent.lower()
        for needles, verb, label in self._SAFE_TASKS:
            if any(n in low for n in needles):
                return verb, label
        return None

    def _tasks_plan(self, ctx: fp.RequestContext) -> dict[str, Any]:
        intent = ((ctx.body or {}).get("intent") or "").strip()
        if not intent:
            raise fp.PortalError(
                "PORTAL-MISSING-FIELD", "field 'intent' is required",
                details={"field": "intent"},
            )
        mapped = self._intent_to_task(intent)
        if mapped is None:
            verbs = sorted({v for _n, v, _l in self._SAFE_TASKS})
            raise fp.PortalError(
                "FDA-PORTAL-AMBIGUOUS",
                "intent does not map to a safe portal task",
                severity="warning",
                action="use one of the safe tasks",
                details={"safe_verbs": verbs, "intent": intent},
            )
        verb, label = mapped
        plan = {"verb": verb, "label": label, "intent": intent}
        return {
            "plan": plan,
            "plan_token": ctx.handler.server.sign_plan(plan),
            "status": "planned",
        }

    def _tasks_execute(self, ctx: fp.RequestContext) -> dict[str, Any]:
        plan = (ctx.body or {}).get("plan") or {}
        verb = plan.get("verb", "")
        if not ctx.handler.server.check_plan((ctx.body or {})["plan_token"], plan):
            raise fp.PortalError(
                "PORTAL-PLAN-STALE",
                "plan token does not match — regenerate the plan",
                http=409, retryable=True, action="regenerate_plan",
            )
        self._task_seq += 1
        task_id = f"task-{self._task_seq}"
        record: dict[str, Any] = {
            "id": task_id, "verb": verb, "label": plan.get("label", verb),
            "stage": "running", "started_at": _now(), "finished_at": None,
            "exit_code": None,
        }
        try:
            result = self._run_safe_task(verb)
            record["stage"] = "completed"
            record["exit_code"] = 0
            record["receipt"] = result
        except fp.PortalError as e:
            record["stage"] = "refused"
            record["exit_code"] = 2
            record["refusal"] = e.code
            record["receipt"] = {"detail": str(e)}
        except Exception as e:
            record["stage"] = "failed"
            record["exit_code"] = 1
            record["receipt"] = {"error": f"{type(e).__name__}: {e}"}
        record["finished_at"] = _now()
        self._tasks.append(record)
        return {
            "status": record["stage"],
            "task": record,
            "actions": [{"kind": "task", "path": verb, "status": record["stage"]}],
        }

    def _run_safe_task(self, verb: str) -> dict[str, Any]:
        if verb == "status":
            return self._status_doc()
        if verb == "doctor":
            ctx = forge_install._ctx(_ctx_args("project", self._root), ())
            return kit.doctor(ctx)
        if verb == "mcp_verify":
            return self._mcp_verify_doc()
        if verb == "graph":
            view = self._graph_view()
            if view is None:
                raise fp.PortalError(
                    "FDA-PORTAL-NO-GRAPH", "no service graph could be built for this workspace",
                    action="add API contracts or detectable sources, then retry",
                )
            return view
        if verb == "scan":
            return self._scan()
        raise fp.PortalError("PORTAL-UNSAFE-TASK", f"task '{verb}' is not in the safe set")

    def _scan(self) -> dict[str, Any]:
        """Real engine run: ``scan_project`` on the workspace — offline,
        deterministic, no target-code execution (the engine contract)."""
        from forge_doctor_api.core.context import ProjectContext
        from forge_doctor_api.scan import scan_project

        report = scan_project(ProjectContext.from_root(self._root))
        sev: dict[str, int] = {}
        for f in report.findings:
            name = getattr(f.severity, "value", str(f.severity)).lower()
            sev[name] = sev.get(name, 0) + 1
        findings = [
            {
                "check_id": f.id,
                "severity": getattr(f.severity, "value", str(f.severity)),
                "confidence": getattr(f.confidence, "value", str(f.confidence)),
                "title": f.title,
                "message": f.description,
                "file": f.source_location.path if f.source_location else None,
                "line": f.source_location.line if f.source_location else None,
                "remediation": f.remediation,
            }
            for f in report.findings[:50]
        ]
        return {
            "schema_version": report.schema_version,
            "project": report.project,
            "analysis_rev": report.analysis_rev,
            "summary": sev,
            "gate_passed": report.gate_passed,
            "findings": findings,
            "unknowns": len(report.unknowns),
            "truncated": len(report.findings) > len(findings),
        }

    # ------------------------------------------------------------------
    # graph — service graph built on demand via graphview.build_view
    # ------------------------------------------------------------------
    def _graph_view(self) -> dict[str, Any] | None:
        try:
            from forge_doctor_api.graphview import build_view
        except Exception:
            return None
        try:
            view = build_view(self._root)
        except Exception:
            return None
        if view is None:
            return None
        return view.to_dict() if hasattr(view, "to_dict") else json.loads(
            json.dumps(view, default=str))

    def _graphs(self) -> dict[str, Any]:
        view = self._graph_view()
        if view is None:
            return {
                "availability": {
                    "state": "no_graph",
                    "detail": "no service graph for this workspace",
                    "unlock": "forge-doctor-api graph . --view",
                },
                "views": [],
                "studio_url": None,
            }
        return {
            "availability": {"state": "available"},
            "views": [view],
            "studio_url": None,
        }

    # ------------------------------------------------------------------
    # docs search — knowledge-program inventory.jsonl title/path, offline
    # ------------------------------------------------------------------
    def _docs_search(self, ctx: fp.RequestContext) -> list[dict[str, Any]]:
        query = (ctx.query.get("q") or [""])[0].strip().lower()
        limit = int((ctx.query.get("limit") or ["20"])[0])
        if not query or not _INVENTORY.is_file():
            return []
        hits: list[dict[str, Any]] = []
        terms = query.split()
        for line in _INVENTORY.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("status") not in (None, "active"):
                continue
            hay = " ".join(str(row.get(k) or "") for k in ("title", "path", "category")).lower()
            if not all(t in hay for t in terms):
                continue
            hits.append({
                "path": row.get("path", ""),
                "title": row.get("title") or Path(row.get("path", "")).stem,
                "excerpt": "",
                "category": row.get("category") or "doc",
            })
            if len(hits) >= limit:
                break
        return hits


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_server(workspace: Path | None = None, *, quiet: bool = True) -> fp.PortalServer:
    return fp.PortalServer(ForgeDoctorApiPortal(workspace), quiet=quiet)
