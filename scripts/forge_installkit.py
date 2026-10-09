"""Forge Installation Contract v1 — reference engine.

Canonical source: ``the-forge/scripts/installkit/forge_installkit.py``.
Vendored per-Forge (``<pkg>/_installkit.py`` or ``scripts/``); keep the
``_INSTALLKIT_VERSION``/``_SOURCE_SHA256`` header intact so drift checks can
compare copies. stdlib-only. Deterministic. Owned-only writes — the sha256
ledger is the single source of truth for what uninstall may remove.

Documents emitted: ``forge/InstallationManifest/v1``,
``forge/InstallReceipt/v1``, ``forge/InstallationHealth/v1``,
``forge/WorkspaceInstall/v1`` (see ``the-forge/docs/portable-installation/``).

Subprocess use is confined to ``_spawn()`` and gated by ``Spec.spawn_ok`` —
a Forge whose package forbids subprocess vendors a stripped copy where
``_spawn`` raises; ``update``/``mcp_verify`` then refuse honestly instead of
silently degrading.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_INSTALLKIT_VERSION = "1.0.0"
# Filled by the vendor step (scripts/installkit/vendor.py) — the sha256 of
# the canonical source body, so drift checks can compare vendored copies.
_SOURCE_SHA256 = "canonical"

SCHEMA_MANIFEST = "forge/InstallationManifest/v1"
SCHEMA_RECEIPT = "forge/InstallReceipt/v1"
SCHEMA_HEALTH = "forge/InstallationHealth/v1"
SCHEMA_WORKSPACE = "forge/WorkspaceInstall/v1"

SCOPES = ("project", "workspace", "user")
PROFILES = ("minimal", "recommended", "full")
HOSTS = ("claude", "devin", "codex", "copilot")
CHECK_STATUSES = ("PASS", "FAIL", "BLOCKED", "UNVERIFIED", "NOT_APPLICABLE")

FORGE_HOME = ".forge"  # under $HOME — the forge-neutral registry
INSTALLATIONS_DIR = "installations"
LEDGER_NAME = "install-ledger.json"
RECEIPTS_DIR = "receipts"
LOCK_NAME = ".install.lock"

# Refusal codes (contract §8) — forge-specific codes may extend these.
E_SCOPE = "FORGE-INSTALL-SCOPE-UNKNOWN"
E_HOST = "FORGE-INSTALL-HOST-UNKNOWN"
E_PROFILE = "FORGE-INSTALL-PROFILE-UNKNOWN"
E_PERM = "FORGE-INSTALL-PERMISSION-DENIED"
E_PYTHON = "FORGE-INSTALL-PYTHON-INCOMPATIBLE"
E_NOTREPO = "FORGE-INSTALL-NOT-A-REPO"
E_NOTAPPROVED = "FORGE-INSTALL-PLAN-NOT-APPROVED"
E_LOCKED = "FORGE-INSTALL-LOCKED"
E_NOTINSTALLED = "FORGE-INSTALL-NOT-INSTALLED"
E_DRIFT = "FORGE-INSTALL-DRIFT-UNREPAIRABLE"
E_UNSUPPORTED = "FORGE-INSTALL-UNSUPPORTED"
E_SPAWN = "FORGE-INSTALL-SPAWN-DISABLED"
E_VERIFY = "FORGE-INSTALL-VERIFY-FAILED"
E_WRITE = "FORGE-INSTALL-WRITE-FAILED"


class InstallError(Exception):
    """Structured refusal — carries the contract error kind."""

    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail

    def document(self, forge_id: str) -> dict[str, Any]:
        return {
            "schema": SCHEMA_RECEIPT,
            "forge_id": forge_id,
            "status": "failed",
            "verification": {"status": "FAIL"},
            "error": {"kind": self.kind, "detail": self.detail},
            "checks": [],
            "managed_files": [],
        }


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha(path.read_bytes())


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _json_bytes(doc: dict[str, Any]) -> bytes:
    return (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _home() -> Path:
    """The user's home — test isolation via HOME/XDG_CONFIG_HOME is the
    caller's job; this function reads the resolved env once."""
    return Path(os.environ.get("FORGE_HOME_OVERRIDE") or Path.home())


def forge_home() -> Path:
    return _home() / FORGE_HOME


def installs_root() -> Path:
    return forge_home() / "installs"


def installations_dir() -> Path:
    return forge_home() / INSTALLATIONS_DIR


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _venv_bin(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def _shim_dir() -> Path:
    # ~/.local/bin on every platform — the pipx/uv convention; on Windows
    # both <cli>.cmd (cmd/PowerShell) and <cli> (Git Bash) are written.
    return _home() / ".local" / "bin"


# --------------------------------------------------------------------------
# Spec — what a Forge declares about itself
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ForgeSpec:
    """What the engine needs to know about a Forge. Everything host- or
    domain-specific enters through ``render_assets``/hooks — the engine is
    generic."""

    forge_id: str  # e.g. "spark-forge-aws" (repo name)
    package: str  # import name
    distribution: str  # pip dist name
    cli_name: str  # console script
    python_spec: str  # e.g. ">=3.10" or ">=3.12,<3.13"
    state_dir: str  # project state dir, e.g. ".sparkforge-aws"
    mcp_command: tuple[str, ...] = ()  # e.g. ("sparkforge-aws","mcp","serve")
    mcp_server_name: str | None = None  # .mcp.json key
    mcp_verify_tool: str | None = None  # no-arg read-only tool for tools/call
    version_cmd: tuple[str, ...] = ("--version",)
    render_assets: Callable[[InstallContext], dict[str, bytes]] | None = None
    marker_files: tuple[str, ...] = ("AGENTS.md", "CLAUDE.md")
    marker_tag: str | None = None  # defaults to forge_id
    marker_body: str = ""
    user_state_dir: str | None = None  # e.g. "~/.sparkforge-aws"
    spawn_ok: bool = True  # False where subprocess is banned
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def tag(self) -> str:
        return self.marker_tag or self.forge_id


@dataclass
class InstallContext:
    spec: ForgeSpec
    scope: str
    root: Path  # resolved target root (project/workspace) or $HOME
    state_dir: Path  # <root>/<spec.state_dir> for project/workspace,
    # <state_dir under HOME> for user
    profile: str
    hosts: tuple[str, ...]
    dry_run: bool = False
    ledger: Ledger | None = None


# --------------------------------------------------------------------------
# Ledger — sha256-keyed ownership of managed files
# --------------------------------------------------------------------------


class Ledger:
    """Records every managed write under a target root.

    ``entries[path] = {sha256, kind, action, managed}`` — only ``managed``
    entries are removable by uninstall; ``adopted`` entries are tracked for
    drift but never deleted."""

    def __init__(self, path: Path):
        self.path = path
        self.doc: dict[str, Any] = _load_json(path, None) or {
            "schema": "forge/InstallLedger/v1",
            "entries": {},
        }

    @classmethod
    def load(cls, state_dir: Path) -> Ledger:
        return cls(state_dir / LEDGER_NAME)

    def save(self) -> None:
        _atomic_write(self.path, _json_bytes(self.doc))

    def record(
        self, rel: str, data: bytes, kind: str, action: str, *, managed: bool = True
    ) -> dict[str, Any]:
        entry = {
            "sha256": _sha(data),
            "kind": kind,
            "action": action,
            "managed": managed,
            "updated_at": _utc_now(),
        }
        self.doc["entries"][rel] = entry
        return {"path": rel, "sha256": entry["sha256"], "kind": kind, "action": action}

    def drop(self, rel: str) -> None:
        self.doc["entries"].pop(rel, None)

    def get(self, rel: str) -> dict[str, Any] | None:
        entry = self.doc["entries"].get(rel)
        return entry if isinstance(entry, dict) else None

    def entries(self) -> dict[str, Any]:
        return dict(self.doc["entries"])

    def owned_paths(self) -> list[str]:
        return sorted(p for p, e in self.doc["entries"].items() if e.get("managed"))

    def drift(self, root: Path, spec: "ForgeSpec | None" = None) -> list[dict[str, str]]:
        """Per-file verdict. When ``spec`` is given the check is kind-aware:
        ``marker`` entries pass when their managed *block* is intact (user
        text outside the markers is never drift); ``mcp`` entries pass when
        the managed ``mcpServers`` key holds canonical command/args (other
        keys are user content); every other entry is compared by sha256."""
        out = []
        for rel, e in sorted(self.doc["entries"].items()):
            p = root / rel
            if not p.exists():
                out.append({"path": rel, "status": "missing"})
                continue
            if spec is not None and _entry_intact(spec, e, rel, p):
                out.append({"path": rel, "status": "ok"})
            else:
                out.append({"path": rel, "status": "modified"})
        return out


def _entry_intact(spec: "ForgeSpec", entry: dict[str, Any], rel: str, path: Path) -> bool:
    """Kind-aware health check for one ledger entry. Marker entries verify
    the managed block only; ``.mcp.json`` verifies the managed server key;
    everything else compares whole-file sha256."""
    kind = entry.get("kind")
    if kind == "marker" and rel in spec.marker_files and spec.marker_body:
        txt = path.read_text(encoding="utf-8")
        return apply_marker_block(txt, spec.tag, spec.marker_body) == txt
    if kind == "mcp" and spec.mcp_server_name:
        cur = _load_json(path, None)
        if not isinstance(cur, dict):
            return False
        want = {"command": spec.mcp_command[0], "args": list(spec.mcp_command[1:])}
        return bool(mcp_set(cur, spec.mcp_server_name, want, spec.tag) == cur)
    return bool(_sha_file(path) == entry["sha256"])


# --------------------------------------------------------------------------
# Locks — refuse concurrent mutation rather than racing
# --------------------------------------------------------------------------


class LockError(InstallError):
    pass


def _pid_alive(pid: int) -> bool | None:
    """Best-effort liveness; ``None`` = cannot determine (do not steal)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes  # noqa: PLC0415

            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        except Exception:
            return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return None


class _Lock:
    """O_EXCL lockfile carrying ``{pid, created_at}``. Stale locks — dead
    holder or older than ``stale_after_s`` — are reclaimed once so an
    interrupted install never bricks the target."""

    def __init__(self, lock: Path, stale_after_s: float = 900.0) -> None:
        self._lock = lock
        self._stale = stale_after_s
        self.held = False
        self.recovered = False

    def __enter__(self) -> _Lock:
        try:
            self._create()
            return self
        except FileExistsError:
            holder = _load_json(self._lock) or {"pid": None}
            stale = self._is_stale(holder)
            if not stale:
                raise LockError(E_LOCKED, f"install lock held at {self._lock} ({holder})") from None
            try:
                self._lock.unlink()
            except OSError as exc:
                raise LockError(
                    E_LOCKED, f"install lock at {self._lock} could not be reclaimed"
                ) from exc
            self.recovered = True
            self._create()
            return self

    def _create(self) -> None:
        fd = os.open(str(self._lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(
            fd,
            _json_bytes({"pid": os.getpid(), "created_at": _utc_now()}),
        )
        os.close(fd)
        self.held = True

    def _is_stale(self, holder: dict[str, Any]) -> bool:
        pid = holder.get("pid")
        if isinstance(pid, int) and pid != os.getpid():
            alive = _pid_alive(pid)
            if alive is False:
                return True
            if alive is True:
                return False
        try:
            age = time.time() - self._lock.stat().st_mtime
        except OSError:
            return False
        return age > self._stale

    def __exit__(self, *exc: object) -> None:
        if self.held:
            try:
                self._lock.unlink()
            except OSError:
                pass


def acquire_lock(state_dir: Path, timeout_s: float = 0.0) -> _Lock:
    """O_EXCL lockfile. Non-blocking by default — contention is a refusal,
    not a hang. Dead/expired locks are reclaimed once."""
    state_dir.mkdir(parents=True, exist_ok=True)
    return _Lock(state_dir / LOCK_NAME)


# --------------------------------------------------------------------------
# Marker blocks — delimited managed regions inside user-owned files
# --------------------------------------------------------------------------


def _markers(tag: str) -> tuple[str, str]:
    return (f"<!-- {tag}:managed:begin -->", f"<!-- {tag}:managed:end -->")


def apply_marker_block(text: str, tag: str, body: str) -> str:
    """Replace-or-append the managed block; user content outside markers is
    never touched."""
    begin, end = _markers(tag)
    block = f"{begin}\n{body.rstrip()}\n{end}"
    if begin in text and end in text:
        pre = text[: text.index(begin)]
        post = text[text.index(end) + len(end) :]
        return pre + block + post
    sep = "" if text.endswith("\n\n") or not text else "\n\n" if text.endswith("\n") else "\n\n"
    return text + sep + block + "\n" if text else block + "\n"


def remove_marker_block(text: str, tag: str) -> str:
    begin, end = _markers(tag)
    if begin in text and end in text:
        pre = text[: text.index(begin)]
        post = text[text.index(end) + len(end) :]
        return (pre.rstrip("\n") + "\n" + post.lstrip("\n")).strip("\n") + "\n"
    return text


def marker_sha(tag: str, body: str) -> str:
    begin, end = _markers(tag)
    return _sha(f"{begin}\n{body.rstrip()}\n{end}".encode())


# --------------------------------------------------------------------------
# .mcp.json — managed key inside a shared config file
# --------------------------------------------------------------------------


def mcp_set(
    doc: dict[str, Any] | None, key: str, value: dict[str, Any], tag: str
) -> dict[str, Any]:
    """Set ``mcpServers.<key>`` inside a managed sub-block. Other servers and
    top-level keys are preserved byte-for-byte as JSON."""
    doc = dict(doc or {})
    servers = dict(doc.get("mcpServers") or {})
    servers[key] = value
    doc["mcpServers"] = servers
    managed = dict(doc.get("_forge_managed") or {})
    managed[tag] = sorted(set(managed.get(tag, [])) | {f"mcpServers.{key}"})
    doc["_forge_managed"] = managed
    return doc


def mcp_unset(doc: dict[str, Any], key: str, tag: str) -> dict[str, Any]:
    doc = dict(doc or {})
    servers = dict(doc.get("mcpServers") or {})
    servers.pop(key, None)
    if servers:
        doc["mcpServers"] = servers
    else:
        doc.pop("mcpServers", None)
    managed = dict(doc.get("_forge_managed") or {})
    managed.pop(tag, None)
    if managed:
        doc["_forge_managed"] = managed
    else:
        doc.pop("_forge_managed", None)
    return doc


# --------------------------------------------------------------------------
# Scope resolution
# --------------------------------------------------------------------------


def _find_vcs_root(start: Path) -> Path | None:
    cur = start.resolve()
    for _ in range(64):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent
    return None


def _find_workspace_root(start: Path) -> Path | None:
    cur = start.resolve()
    for _ in range(64):
        for name in (
            "forge.workspace.yaml",
            "forge.workspace.json",
            ".forge-workspace",
            "pyproject.toml",
        ):
            if (cur / name).exists():
                if name == "pyproject.toml" and not _is_workspace_pyproject(cur):
                    cur = cur.parent
                    continue
                return cur
        if cur.parent == cur:
            return None
        cur = cur.parent
    return None


def _is_workspace_pyproject(root: Path) -> bool:
    try:
        txt = (root / "pyproject.toml").read_text(encoding="utf-8")
        return "tool.forge.workspace" in txt or "tool.uv.workspace" in txt
    except OSError:
        return False


def _find_state_root(spec: ForgeSpec, cwd: Path) -> Path | None:
    """Nearest ancestor (or cwd) already carrying `spec.state_dir` — the dir
    is an installed project even without a VCS checkout."""
    cur = Path(cwd).resolve()
    while True:
        if (cur / spec.state_dir).is_dir():
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent


def resolve_scope(spec: ForgeSpec, scope: str, cwd: Path, explicit: Path | None) -> Path:
    if scope not in SCOPES:
        raise InstallError(E_SCOPE, f"scope {scope!r} — expected {SCOPES}")
    if scope == "user":
        return _home()
    root = explicit or _find_vcs_root(cwd)
    if scope == "workspace":
        ws = _find_workspace_root(explicit or cwd)
        return ws or (explicit or _find_vcs_root(cwd) or cwd)
    if root is None:
        if explicit:
            return explicit
        state_root = _find_state_root(spec, cwd)
        if state_root is not None:
            return state_root
        raise InstallError(E_NOTREPO, f"{cwd}: no VCS root — pass --root or cd into a repo")
    return root


def state_dir_for(spec: ForgeSpec, scope: str, root: Path) -> Path:
    if scope == "user":
        base = spec.user_state_dir or f"~/.{spec.forge_id.replace('-', '_')}"
        return Path(os.path.expandvars(os.path.expanduser(base)))
    return root / spec.state_dir


# --------------------------------------------------------------------------
# The engine
# --------------------------------------------------------------------------


def _host_dirs(host: str, scope: str) -> list[str]:
    """Project/user roots a host reads its assets from."""
    if scope == "user":
        return {
            "claude": ["~/.claude/skills", "~/.claude/agents"],
            "devin": ["~/.devin/skills", "~/.agents/skills", "~/.agents/agents"],
            "codex": ["~/.codex", "~/.agents/skills", "~/.agents/agents"],
            "copilot": ["~/.agents/skills", "~/.agents/agents"],
        }.get(host, [])
    return {
        "claude": [".claude/skills", ".claude/agents"],
        "devin": [".devin/skills", ".agents/skills", ".agents/agents"],
        "codex": [".agents/skills", ".agents/agents", ".codex"],
        "copilot": [".agents/skills", ".agents/agents", ".github/skills"],
    }.get(host, [])


def profile_asset_kinds(profile: str) -> tuple[str, ...]:
    return {
        "minimal": ("config", "mcp", "marker", "state"),
        "recommended": ("config", "mcp", "marker", "state", "skill"),
        "full": ("config", "mcp", "marker", "state", "skill", "agent"),
    }[profile]


def plan(ctx: InstallContext) -> dict[str, Any]:
    """Pure plan — what *would* change. Never writes."""
    assets = ctx.spec.render_assets(ctx) if ctx.spec.render_assets else {}
    kinds = set(profile_asset_kinds(ctx.profile))
    files = []
    for rel in sorted(assets):
        kind = _asset_kind(rel)
        if kind not in kinds:
            continue
        target = ctx.root / rel
        exists = target.exists()
        files.append(
            {
                "path": rel,
                "kind": kind,
                "action": "update" if exists else "create",
                "sha256": _sha(assets[rel]),
            }
        )
    markers = [
        {"file": m, "marker": ctx.spec.tag}
        for m in ctx.spec.marker_files
        if (ctx.root / m).exists() or m == "AGENTS.md"
    ]
    return {
        "schema": SCHEMA_RECEIPT,
        "forge_id": ctx.spec.forge_id,
        "operation": "install",
        "scope": ctx.scope,
        "profile": ctx.profile,
        "target_root": str(ctx.root),
        "hosts": list(ctx.hosts),
        "dry_run": ctx.dry_run,
        "status": "planned",
        "planned_files": files,
        "planned_markers": markers,
        "managed_files": [],
        "checks": [],
        "verification": {"status": "UNVERIFIED"},
    }


def _asset_kind(rel: str) -> str:
    if "/skills/" in f"/{rel}" or rel.endswith("SKILL.md"):
        return "skill"
    if "/agents/" in f"/{rel}" or "agent" in Path(rel).name.lower():
        return "agent"
    if Path(rel).name == ".mcp.json" or "mcp" in rel:
        return "mcp"
    if rel.startswith((".", "")) and Path(rel).suffix in (".json", ".yaml", ".yml", ".toml"):
        return "config"
    return "state"


def _rollback_writes(ctx: InstallContext, created: list[Path], backups: dict[Path, Path]) -> None:
    """§14.3.7 — revert managed writes from a failed apply: restore pre-state
    backups, remove files created by the operation. User-owned files were
    never touched (conflicts refuse the plan before this point), so rollback
    can only undo our own writes."""
    for target, bak in backups.items():
        try:
            _atomic_write(target, bak.read_bytes())
        except OSError:
            pass
    removed: list[str] = []
    for target in created:
        try:
            target.unlink()
            removed.append(str(target.relative_to(ctx.root)))
        except (OSError, ValueError):
            pass
    _prune_empty_dirs(ctx.root, removed)


def apply_install(ctx: InstallContext, *, approved: bool = False) -> dict[str, Any]:
    """The governed write path. Idempotent: unchanged assets are not
    re-touched; pre-existing identical files are adopted, never owned."""
    if not approved and not ctx.dry_run:
        raise InstallError(
            E_NOTAPPROVED, "install requires --yes/--approve or --dry-run; the plan is the contract"
        )
    p = plan(ctx)
    if ctx.dry_run:
        p["status"] = "planned"
        return p

    files: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    ledger = ctx.ledger or Ledger.load(ctx.state_dir)
    # §14.3 journal — every write is either a creation (removable) or an
    # overwrite with a pre-state snapshot; on failure the managed half is
    # reverted before the error propagates.
    created: list[Path] = []
    backups: dict[Path, Path] = {}

    def _snapshot(target: Path, rel: str) -> None:
        bak = ctx.state_dir / "backups" / rel
        bak.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(bak, target.read_bytes())
        backups[target] = bak

    try:
        assets = ctx.spec.render_assets(ctx) if ctx.spec.render_assets else {}
        kinds = set(profile_asset_kinds(ctx.profile))
        ctx_bytes = {"skill": 0, "agent": 0, "managed": 0}
        for rel in sorted(assets):
            kind = _asset_kind(rel)
            if kind not in kinds:
                continue
            data = assets[rel]
            if kind in ("skill", "agent"):
                ctx_bytes[kind] += len(data)
            ctx_bytes["managed"] += len(data)
            target = ctx.root / rel
            existing_entry = ledger.get(rel)
            if target.exists():
                cur = target.read_bytes()
                if cur == data:
                    action = "unchanged" if existing_entry else "adopted"
                    files.append(
                        ledger.record(rel, data, kind, action, managed=bool(existing_entry))
                    )
                    continue
                if existing_entry is None:
                    # Pre-existing foreign file — never overwrite silently.
                    files.append(
                        {
                            "path": rel,
                            "sha256": _sha(cur),
                            "kind": kind,
                            "action": "unchanged",
                            "note": "user-owned, not managed — skipped",
                        }
                    )
                    continue
                _snapshot(target, rel)
            else:
                created.append(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(target, data)
            files.append(ledger.record(rel, data, kind, "updated" if existing_entry else "created"))

        # Marker blocks in AGENTS.md / CLAUDE.md — delimited, user content kept.
        if "marker" in kinds and ctx.spec.marker_body:
            for m in ctx.spec.marker_files:
                target = ctx.root / m
                if not target.exists() and m != "AGENTS.md":
                    continue  # never create CLAUDE.md unprompted; AGENTS.md is the generic contract
                original = target.read_text(encoding="utf-8") if target.exists() else ""
                updated = apply_marker_block(original, ctx.spec.tag, ctx.spec.marker_body)
                if updated == original:
                    markers.append(
                        {
                            "file": m,
                            "marker": ctx.spec.tag,
                            "sha256": marker_sha(ctx.spec.tag, ctx.spec.marker_body),
                        }
                    )
                    continue
                if target.exists():
                    _snapshot(target, m)
                else:
                    created.append(target)
                _atomic_write(target, updated.encode("utf-8"))
                ledger.record(
                    m, updated.encode(), "marker", "updated" if ledger.get(m) else "created"
                )
                markers.append(
                    {
                        "file": m,
                        "marker": ctx.spec.tag,
                        "sha256": marker_sha(ctx.spec.tag, ctx.spec.marker_body),
                    }
                )

        # .mcp.json managed key — only when the forge has an MCP server.
        mcp_entries: list[dict[str, Any]] = []
        if ctx.spec.mcp_server_name and "mcp" in kinds:
            mcp_file = ctx.root / ".mcp.json"
            entry = {"command": ctx.spec.mcp_command[0], "args": list(ctx.spec.mcp_command[1:])}
            if mcp_file.exists():
                cur = _load_json(mcp_file, None)
                if cur is None:
                    checks.append(
                        {
                            "id": "mcp-json",
                            "status": "FAIL",
                            "detail": ".mcp.json exists but is not JSON",
                        }
                    )
                else:
                    new = mcp_set(cur, ctx.spec.mcp_server_name, entry, ctx.spec.tag)
                    if _json_bytes(new) != mcp_file.read_bytes():
                        _snapshot(mcp_file, ".mcp.json")
                        _atomic_write(mcp_file, _json_bytes(new))
                        ledger.record(
                            ".mcp.json",
                            _json_bytes(new),
                            "mcp",
                            "updated" if ledger.get(".mcp.json") else "created",
                        )
                    mcp_entries.append(
                        {
                            "server": ctx.spec.mcp_server_name,
                            "file": ".mcp.json",
                            "key": f"managed:{ctx.spec.tag}",
                            "action": "set",
                        }
                    )
            else:
                new = mcp_set(None, ctx.spec.mcp_server_name, entry, ctx.spec.tag)
                created.append(mcp_file)
                _atomic_write(mcp_file, _json_bytes(new))
                ledger.record(".mcp.json", _json_bytes(new), "mcp", "created")
                mcp_entries.append(
                    {
                        "server": ctx.spec.mcp_server_name,
                        "file": ".mcp.json",
                        "key": f"managed:{ctx.spec.tag}",
                        "action": "created",
                    }
                )
    except InstallError:
        _rollback_writes(ctx, created, backups)
        raise
    except Exception as exc:
        _rollback_writes(ctx, created, backups)
        raise InstallError(
            E_WRITE, f"install failed at write stage; managed writes reverted: {exc}"
        ) from exc

    ledger.save()
    written = sum(1 for f in files if f.get("action") in ("created", "updated"))
    checks.append({"id": "files-written", "status": "PASS", "detail": f"{written} writes"})
    receipt = {
        "schema": SCHEMA_RECEIPT,
        "receipt_id": f"sha256:{_sha(_json_bytes({'f': files, 'm': markers}))}",
        "forge_id": ctx.spec.forge_id,
        "operation": "install",
        "scope": ctx.scope,
        "profile": ctx.profile,
        "target_root": str(ctx.root),
        "host": ",".join(ctx.hosts) or None,
        "dry_run": False,
        "managed_files": files,
        "managed_markers": markers,
        "mcp": mcp_entries,
        # Context-budget metrics — only what is observable at write time
        # (§13.2). Token counts are never invented: hosts that supply
        # them report through their own telemetry.
        "context": {
            "profile": ctx.profile,
            "skills_bytes": ctx_bytes["skill"],
            "agents_bytes": ctx_bytes["agent"],
            "managed_bytes": ctx_bytes["managed"] or None,
            "mcp_entries": len(mcp_entries) or None,
        },
        "env": {"python": platform.python_version()},
        "checks": checks,
        "verification": {
            "status": "PASS"
            if all(c["status"] in ("PASS", "NOT_APPLICABLE") for c in checks)
            else "FAIL"
        },
        "status": "completed",
        "rollback": {"available": bool(files), "restore": "ledger"},
        "created_at": _utc_now(),
        "created_by": f"{ctx.spec.distribution}",
    }
    _write_receipt(ctx.state_dir, receipt)
    return receipt


def _write_receipt(state_dir: Path, receipt: dict[str, Any]) -> Path:
    ts = _utc_now().replace(":", "").replace("-", "")
    path = state_dir / RECEIPTS_DIR / f"{receipt['operation']}-{ts}.json"
    _atomic_write(path, _json_bytes(receipt))
    return path


# --------------------------------------------------------------------------
# status / doctor / repair / uninstall
# --------------------------------------------------------------------------


def status(ctx: InstallContext) -> dict[str, Any]:
    ledger = Ledger.load(ctx.state_dir)
    drift = ledger.drift(ctx.root, ctx.spec)
    ok = sum(1 for d in drift if d["status"] == "ok")
    bad = [d for d in drift if d["status"] != "ok"]
    receipts = (
        sorted((ctx.state_dir / RECEIPTS_DIR).glob("*.json"))
        if (ctx.state_dir / RECEIPTS_DIR).is_dir()
        else []
    )
    return {
        "schema": SCHEMA_HEALTH,
        "forge_id": ctx.spec.forge_id,
        "scope": ctx.scope,
        "target_root": str(ctx.root),
        "state_dir": str(ctx.state_dir),
        "ledger_entries": len(ledger.entries()),
        "drift": {
            "ok": ok,
            "modified": [d for d in bad if d["status"] == "modified"],
            "missing": [d for d in bad if d["status"] == "missing"],
        },
        "receipts": [r.name for r in receipts],
        "status": ("healthy" if not bad else "degraded" if ok else "broken")
        if ledger.entries()
        else "unverified",
        "checked_at": _utc_now(),
    }


def doctor(ctx: InstallContext) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    ledger = Ledger.load(ctx.state_dir)
    installed = ledger.entries()
    checks.append(
        {
            "id": "ledger",
            "status": "PASS" if installed else "UNVERIFIED",
            "detail": f"{len(installed)} managed entries",
            "repairable": False,
        }
    )
    for d in ledger.drift(ctx.root, ctx.spec):
        if d["status"] != "ok":
            checks.append(
                {
                    "id": f"drift:{d['path']}",
                    "status": "FAIL",
                    "detail": d["status"],
                    "repairable": True,
                }
            )
    if ctx.spec.mcp_server_name:
        mcp_file = ctx.root / ".mcp.json"
        if mcp_file.exists():
            doc = _load_json(mcp_file, None)
            ok = isinstance(doc, dict) and ctx.spec.mcp_server_name in doc.get("mcpServers", {})
            checks.append(
                {"id": "mcp-config", "status": "PASS" if ok else "FAIL", "repairable": not ok}
            )
        else:
            checks.append(
                {
                    "id": "mcp-config",
                    "status": "FAIL",
                    "detail": ".mcp.json missing",
                    "repairable": True,
                }
            )
        mcp_check = mcp_verify(ctx.spec)
        checks.append(mcp_check)
        invoke = mcp_check.get("invoke")
        if isinstance(invoke, dict):  # hoisted so a FAIL degrades health
            checks.append(
                {
                    "id": "mcp-invoke",
                    "status": invoke["status"],
                    "detail": f"{invoke['tool']}: {invoke['detail']}",
                    "repairable": False,
                }
            )
    overall = "healthy"
    if any(c["status"] == "FAIL" for c in checks):
        overall = "degraded" if installed else "broken"
    elif not installed:
        overall = "unverified"
    handshake = next((c for c in checks if c.get("id") == "mcp-handshake"), None)
    return {
        "schema": SCHEMA_HEALTH,
        "forge_id": ctx.spec.forge_id,
        "status": overall,
        "checks": checks,
        # Observable context budget only (§13.2): tools the server
        # actually enumerated; nothing inferred.
        "context": {
            "profile": ctx.profile,
            "managed_entries": len(installed),
            "tools_exposed": len(handshake["tools"])
            if isinstance(handshake, dict) and isinstance(handshake.get("tools"), list)
            else None,
        },
        "checked_at": _utc_now(),
        "repair_hint": f"{ctx.spec.cli_name} repair"
        if any(c.get("repairable") for c in checks)
        else None,
    }


def _repair_content(
    ctx: InstallContext, rel: str, entry: dict[str, Any], assets: dict[str, bytes], target: Path
) -> bytes | None:
    """Canonical bytes for a drifted *managed* entry, or ``None`` when the
    entry cannot be re-asserted. Marker entries re-heal the managed block
    inside the user's file (content outside the markers survives);
    ``.mcp.json`` re-sets the managed server key preserving sibling keys;
    whole-file managed assets re-assert the rendered bytes."""
    kind = entry.get("kind")
    if kind == "marker" and rel in ctx.spec.marker_files:
        original = target.read_text(encoding="utf-8") if target.exists() else ""
        return apply_marker_block(original, ctx.spec.tag, ctx.spec.marker_body).encode("utf-8")
    if kind == "mcp" and ctx.spec.mcp_server_name:
        cur = _load_json(target, {})
        if not isinstance(cur, dict):
            cur = {}
        want = {"command": ctx.spec.mcp_command[0], "args": list(ctx.spec.mcp_command[1:])}
        new = mcp_set(cur, ctx.spec.mcp_server_name, want, ctx.spec.tag)
        return _json_bytes(new)
    return assets.get(rel)


def repair(ctx: InstallContext) -> dict[str, Any]:
    """Re-assert drifted *managed* content: missing entries are restored,
    damaged managed regions (marker block, mcp key) are healed inside the
    user's file, drifted managed assets are re-asserted. Entries with no
    canonical source land in ``skipped`` as unrepairable; foreign content is
    never touched."""
    ledger = Ledger.load(ctx.state_dir)
    drift = [d for d in ledger.drift(ctx.root, ctx.spec) if d["status"] != "ok"]
    fixed, kept, skipped = [], [], []
    assets = ctx.spec.render_assets(ctx) if ctx.spec.render_assets else {}
    for d in drift:
        rel = d["path"]
        entry = ledger.get(rel)
        target = ctx.root / rel
        if entry is None:
            skipped.append(rel)
            continue
        data = _repair_content(ctx, rel, entry, assets, target)
        if data is None:
            skipped.append(rel)
            continue
        if target.exists() and target.read_bytes() == data:
            kept.append(rel)
            continue
        if target.exists():
            bak = ctx.state_dir / "backups" / rel
            bak.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(bak, target.read_bytes())
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, data)
        ledger.record(
            rel, data, entry["kind"], "restored" if d["status"] == "missing" else "rehealed"
        )
        fixed.append(rel)
    ledger.save()
    return {
        "schema": SCHEMA_RECEIPT,
        "forge_id": ctx.spec.forge_id,
        "operation": "repair",
        "scope": ctx.scope,
        "target_root": str(ctx.root),
        "repaired": fixed,
        "kept": kept,
        "skipped": skipped,
        "managed_files": [],
        "checks": [
            {
                "id": "repair",
                "status": "PASS" if not skipped else "FAIL",
                "detail": (f"{len(fixed)} restored, {len(kept)} kept, {len(skipped)} skipped"),
            }
        ],
        "verification": {"status": "PASS" if not skipped else "FAIL"},
        "status": "completed",
        "created_at": _utc_now(),
    }


def uninstall(ctx: InstallContext, *, purge_state: bool = False) -> dict[str, Any]:
    """Remove only ledger-owned files. Adopted and user files survive;
    marker blocks are excised; the .mcp.json managed key is unset."""
    ledger = Ledger.load(ctx.state_dir)
    removed, kept = [], []
    for rel in ledger.owned_paths():
        target = ctx.root / rel
        if rel in ctx.spec.marker_files and target.exists():
            # marker files: excise the block, keep the file
            txt = remove_marker_block(target.read_text(encoding="utf-8"), ctx.spec.tag)
            if txt.strip():
                _atomic_write(target, txt.encode())
                kept.append(rel)
            else:
                target.unlink()
                removed.append(rel)
            ledger.drop(rel)
            continue
        if target.exists():
            # Re-verify sha256 before deleting — a user-modified managed
            # file is treated as user-owned and kept.
            reg = ledger.get(rel)
            if reg is None or _sha_file(target) != reg["sha256"]:
                kept.append(rel)
                ledger.drop(rel)
                continue
            target.unlink()
            removed.append(rel)
        ledger.drop(rel)
    if ctx.spec.mcp_server_name:
        mcp_file = ctx.root / ".mcp.json"
        if mcp_file.exists():
            doc = _load_json(mcp_file, None)
            if isinstance(doc, dict):
                new = mcp_unset(doc, ctx.spec.mcp_server_name, ctx.spec.tag)
                if new.get("mcpServers") or len(new) > 0:
                    _atomic_write(mcp_file, _json_bytes(new))
                else:
                    mcp_file.unlink()
                ledger.drop(".mcp.json")
    _prune_empty_dirs(ctx.root, removed)
    if purge_state and ctx.state_dir.exists():
        import shutil

        shutil.rmtree(ctx.state_dir, ignore_errors=True)
        # prune now-empty forge state ancestors (e.g. .forge-doctor-data/)
        parent = ctx.state_dir.parent
        while parent != ctx.root and ctx.root in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    else:
        ledger.save()
    receipt = {
        "schema": SCHEMA_RECEIPT,
        "forge_id": ctx.spec.forge_id,
        "operation": "uninstall",
        "scope": ctx.scope,
        "target_root": str(ctx.root),
        "removed": removed,
        "kept": kept,
        "managed_files": [],
        "checks": [
            {
                "id": "uninstall",
                "status": "PASS",
                "detail": f"{len(removed)} removed, {len(kept)} kept",
            }
        ],
        "verification": {"status": "PASS"},
        "status": "completed",
        "created_at": _utc_now(),
    }
    if not purge_state:
        _write_receipt(ctx.state_dir, receipt)
    return receipt


def _prune_empty_dirs(root: Path, removed: list[str]) -> None:
    """Remove empty parent dirs of deleted managed files, stopping at the
    first non-empty ancestor or ``root``. User dirs are never touched —
    ``rmdir`` refuses on non-empty directories by design."""
    seen: set[Path] = set()
    for rel in removed:
        parent = (root / rel).parent
        while parent != root and root in parent.parents and parent not in seen:
            try:
                parent.rmdir()
            except OSError:
                break
            seen.add(parent)
            parent = parent.parent


# --------------------------------------------------------------------------
# ~/.forge registry — the forge-neutral installations directory
# --------------------------------------------------------------------------


def manifest_for(
    spec: ForgeSpec,
    *,
    install_root: Path,
    venv: Path | None,
    version: str,
    source: dict[str, Any],
    shim: Path | None,
) -> dict[str, Any]:
    doc = {
        "schema": SCHEMA_MANIFEST,
        "forge_id": spec.forge_id,
        "package": spec.package,
        "distribution": spec.distribution,
        "cli": {"name": spec.cli_name, "version_cmd": [spec.cli_name, *spec.version_cmd]},
        "version": version,
        "install_root": str(install_root),
        "python": {
            "executable": str(_venv_python(venv)) if venv else sys.executable,
            "version": platform.python_version(),
            "satisfies": spec.python_spec,
        },
        "source": source,
        "installed_at": _utc_now(),
        "installed_by": {"agent": "forge_bootstrap", "version": _INSTALLKIT_VERSION},
    }
    if venv:
        doc["venv"] = str(venv)
    if shim:
        cli_doc = doc["cli"]
        if isinstance(cli_doc, dict):
            cli_doc["shim"] = str(shim)
    if spec.mcp_server_name:
        mcp_doc: dict[str, Any] = {
            "server_name": spec.mcp_server_name,
            "command": list(spec.mcp_command),
            "verified": False,
        }
        if spec.mcp_verify_tool:
            mcp_doc["verify_tool"] = spec.mcp_verify_tool
        doc["mcp"] = mcp_doc
    return doc


def register_installation(manifest: dict[str, Any]) -> Path:
    path = installations_dir() / f"{manifest['forge_id']}.json"
    _atomic_write(path, _json_bytes(manifest))
    return path


def deregister_installation(forge_id: str) -> bool:
    path = installations_dir() / f"{forge_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def installed_forges() -> list[dict[str, Any]]:
    out = []
    d = installations_dir()
    if d.is_dir():
        for f in sorted(d.glob("*.json")):
            doc = _load_json(f, None)
            if isinstance(doc, dict):
                doc["_manifest_path"] = str(f)
                out.append(doc)
    return out


# --------------------------------------------------------------------------
# Workspace members — multi-repo discovery (``forge/WorkspaceInstall/v1``)
# --------------------------------------------------------------------------


def discover_projects(root: Path, *, max_depth: int = 2) -> list[Path]:
    """Independent repos under a workspace root: directories containing
    ``.git``. ``root`` itself is included when it is a repository; nested
    checkouts are found up to ``max_depth`` levels deep. Never descends
    into a discovered repo (its inner modules stay isolated)."""
    root = Path(root).resolve()
    found: list[Path] = []
    if (root / ".git").exists():
        found.append(root)

    def _walk(d: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir())
        except OSError:
            return
        for child in children:
            if child.name.startswith("."):  # hidden dirs incl. .git internals
                continue
            if (child / ".git").exists():
                found.append(child.resolve())
            else:
                _walk(child, depth + 1)

    _walk(root, 1)
    return found


def member_precedence(member: Path, spec: ForgeSpec) -> str | None:
    """``"project"`` when a member already carries a project-scope install
    or its own managed MCP key for this forge — local specializes the
    workspace install and must never be silently widened. ``None`` when
    the member is a clean adoption target."""
    state = member / spec.state_dir
    if state.is_dir():
        return "project"
    mcp = member / ".mcp.json"
    if spec.mcp_server_name and mcp.exists():
        doc = _load_json(mcp, None)
        if isinstance(doc, dict) and spec.mcp_server_name in (doc.get("mcpServers") or {}):
            return "project"
    return None


# --------------------------------------------------------------------------
# Spawn-gated ops — refused honestly where subprocess is unavailable
# --------------------------------------------------------------------------


def _spawn(
    spec: ForgeSpec,
    cmd: list[str],
    *,
    timeout: int = 30,
    input_bytes: bytes | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, bytes, bytes]:
    if not spec.spawn_ok:
        raise InstallError(
            E_SPAWN,
            f"{spec.forge_id}: subprocess disabled by policy — "
            "run the equivalent scripts/ helper instead",
        )
    # --vendor-strip:subprocess-begin
    import subprocess  # noqa: PLC0415 - lazy: spawn_ok gates reachability

    proc = subprocess.run(  # noqa: S603 — cmd is the declared spec
        cmd, capture_output=True, timeout=timeout, input=input_bytes, env=env
    )
    return proc.returncode, proc.stdout, proc.stderr
    # --vendor-strip:subprocess-end


def mcp_verify(spec: ForgeSpec, *, timeout: int = 20) -> dict[str, Any]:
    """JSON-RPC stdio handshake: initialize → notifications/initialized →
    tools/list. Reports honestly — never infers success from file presence."""
    if not spec.mcp_server_name or not spec.mcp_command:
        return {
            "id": "mcp-handshake",
            "status": "NOT_APPLICABLE",
            "detail": "no MCP server declared",
        }
    if not spec.spawn_ok:
        return {
            "id": "mcp-handshake",
            "status": "BLOCKED",
            "detail": "subprocess disabled by policy",
        }
    exe = spec.mcp_command[0]
    if not (os.sep in exe or (os.altsep and os.altsep in exe)):
        import shutil  # noqa: PLC0415

        if shutil.which(exe) is None:
            return {
                "id": "mcp-handshake",
                "status": "BLOCKED",
                "detail": f"{exe!r} not resolvable on PATH — install incomplete",
            }
    try:
        import subprocess  # noqa: PLC0415

        proc = subprocess.Popen(  # noqa: S603 — command is the declared spec
            list(spec.mcp_command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        # CLI not on PATH — the install is incomplete, not defective.
        return {
            "id": "mcp-handshake",
            "status": "BLOCKED",
            "detail": f"cannot spawn {spec.mcp_command[0]!r}: {exc}",
        }
    except OSError as exc:
        return {
            "id": "mcp-handshake",
            "status": "FAIL",
            "detail": f"cannot spawn {spec.mcp_command[0]!r}: {exc}",
        }
    if proc.stdin is None or proc.stdout is None:
        proc.kill()
        return {"id": "mcp-handshake", "status": "FAIL", "detail": "stdio pipes unavailable"}
    try:
        out = _mcp_handshake(proc, spec, timeout)
    except Exception as exc:  # handshake failures are FAIL, not crashes
        out = {"id": "mcp-handshake", "status": "FAIL", "detail": str(exc)}
    killed = False
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
            killed = True
        except Exception:  # noqa: S110 — best-effort kill after terminate
            pass
    stderr_tail = b""
    try:
        if proc.stderr is not None:
            stderr_tail = proc.stderr.read()[-400:]
    except Exception:  # noqa: S110 — server stderr is best-effort evidence
        pass
    out["process"] = {
        "exit": ("clean" if proc.returncode == 0 else "killed" if killed else "terminated"),
        "returncode": proc.returncode,
        "stderr_tail": stderr_tail.decode(errors="replace").strip()[-200:] or None,
    }
    return out


def _mcp_handshake(proc: Any, spec: ForgeSpec, timeout: int) -> dict[str, Any]:
    """initialize → initialized → tools/list (+ tools/call when the spec
    declares a no-arg ``mcp_verify_tool``). Returns the check dict; the
    caller attaches process-exit evidence."""
    assert proc.stdin is not None and proc.stdout is not None
    req = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "forge-verify", "version": "1"},
            },
        }
    ).encode()
    proc.stdin.write(req + b"\n")
    proc.stdin.write(
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode() + b"\n"
    )
    proc.stdin.write(
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode() + b"\n"
    )
    if spec.mcp_verify_tool:
        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": spec.mcp_verify_tool, "arguments": {}},
                }
            ).encode()
            + b"\n"
        )
    proc.stdin.flush()
    # selectors cannot watch pipes on Windows — a daemon reader thread
    # draining stdout into a queue is the portable deadline mechanism.
    import queue  # noqa: PLC0415
    import threading  # noqa: PLC0415
    import time  # noqa: PLC0415

    lines: "queue.Queue[bytes]" = queue.Queue()

    def _drain() -> None:
        for ln in proc.stdout:
            lines.put(ln)

    threading.Thread(target=_drain, daemon=True).start()
    tools: list[str] = []
    got_init = False
    invoke: dict[str, Any] | None = (
        {"tool": spec.mcp_verify_tool, "status": "UNVERIFIED", "detail": "no response"}
        if spec.mcp_verify_tool
        else None
    )
    want_ids = {1, 2} | ({3} if spec.mcp_verify_tool else set())
    deadline = time.monotonic() + timeout
    while want_ids:
        remain = deadline - time.monotonic()
        if remain <= 0:
            break
        try:
            line = lines.get(timeout=remain)
        except queue.Empty:
            break
        if not line:
            break
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid = msg.get("id")
        if mid == 1 and "result" in msg:
            got_init = True
            want_ids.discard(1)
        elif mid == 2 and "result" in msg:
            tools = [t.get("name", "?") for t in msg["result"].get("tools", [])]
            want_ids.discard(2)
        elif mid == 3 and invoke is not None:
            want_ids.discard(3)
            if "error" in msg:
                invoke["status"] = "FAIL"
                invoke["detail"] = str(msg["error"])[:200]
            else:
                result = msg.get("result") or {}
                if result.get("isError"):
                    invoke["status"] = "FAIL"
                    invoke["detail"] = "tool reported isError"
                else:
                    invoke["status"] = "PASS"
                    invoke["detail"] = "structured result returned"
    if not got_init:
        return {"id": "mcp-handshake", "status": "FAIL", "detail": "no initialize response"}
    out: dict[str, Any] = {
        "id": "mcp-handshake",
        "status": "PASS",
        "detail": f"{len(tools)} tools",
        "tools": tools[:50],
    }
    if invoke is not None:
        out["invoke"] = invoke
    return out


def cli_version(spec: ForgeSpec, *, timeout: int = 15) -> str | None:
    try:
        code, out, _ = _spawn(spec, [spec.cli_name, *spec.version_cmd], timeout=timeout)
        if code == 0:
            return out.decode(errors="replace").strip().splitlines()[0]
    except (InstallError, Exception):
        return None
    return None


# --------------------------------------------------------------------------
# Launcher shims — make <cli> resolvable in a new terminal
# --------------------------------------------------------------------------


def write_launcher(spec: ForgeSpec, venv: Path) -> Path:
    """Write a shim into the shim dir that delegates to the venv's console
    script. POSIX gets an exec wrapper; Windows gets a .cmd + a bash shim."""
    bindir = _venv_bin(venv)
    real = bindir / (spec.cli_name + (".exe" if os.name == "nt" else ""))
    if not real.exists():
        real = bindir / spec.cli_name
    shim_dir = _shim_dir()
    shim_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        cmd = shim_dir / f"{spec.cli_name}.cmd"
        cmd.write_text(f'@echo off\r\n"{real}" %*\r\n', encoding="utf-8")
        bash = shim_dir / spec.cli_name
        bash.write_text(f'#!/bin/sh\nexec "{real}" "$@"\n', encoding="utf-8")
        return cmd
    shim = shim_dir / spec.cli_name
    shim.write_text(f'#!/bin/sh\nexec "{real}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    return shim


def path_guidance() -> str | None:
    """None when the shim dir is already on PATH; else the line to add."""
    shim = _shim_dir()
    path = os.environ.get("PATH", "")
    if str(shim) in path.split(os.pathsep):
        return None
    if os.name == "nt":
        return f'setx PATH "%PATH%;{shim}"  # then open a new terminal'
    shell = Path(os.environ.get("SHELL", "/bin/sh")).name
    rc = {"zsh": "~/.zshrc", "bash": "~/.bashrc"}.get(shell, "~/.profile")
    return f"echo 'export PATH=\"{shim}:$PATH\"' >> {rc}  # then restart the shell"


__all__ = [name for name in dir() if not name.startswith("_")]
