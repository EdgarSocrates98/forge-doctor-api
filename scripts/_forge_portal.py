#!/usr/bin/env python3
# forge_portal.py — Forge Portal local server (stdlib-only, vendored).
#
# Byte-parity vendored module: every Forge ships this file verbatim as
# `<pkg>/_forge_portal.py`. It knows NOTHING about any specific forge —
# a forge supplies a PortalAdapter (see `PORTAL ADAPTER CONTRACT` below)
# which registers typed operations. The server handles HTTP, sessions,
# CSRF, payload/rate limits, plan tokens, SSE and static assets.
#
# Security model (docs/fase0/security-matrix.md):
#   - bind 127.0.0.1 only, ephemeral port
#   - 128-bit session token → X-Forge-Session header on every /api call
#   - POST: Origin loopback allowlist + Content-Type: application/json
#   - no shell: operations are the adapter's typed registry only
#   - mutating ops need `confirm` literal and, when applicable, plan_token
#   - 1 MiB payload cap, 10 mutating POST/min per process, per-op timeout
#   - responses pass through a secret-redacting allowlist scrub

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import socket
import threading
import time
import urllib.parse
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SCHEMA = "forge/PortalApi/1"
API_PREFIX = "/api/v1"
SESSION_HEADER = "X-Forge-Session"
SESSION_COOKIE = "forge_session"
MAX_BODY = 1 << 20  # 1 MiB
MUTATION_WINDOW_S = 60.0
MUTATION_LIMIT = 10
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'self'; form-action 'self'"
)

_SECRET_KEYS = ("token", "secret", "password", "cookie", "authorization", "api_key", "apikey", "credential")

# Keys that LOOK secret-shaped but are client-usable by design: the plan
# token must round-trip through the client for confirm-then-apply to work.
# Everything else matching _SECRET_KEYS is scrubbed.
_REDACT_EXEMPT = frozenset({"plan_token"})


# ---------------------------------------------------------------------------
# errors / refusals


class PortalError(Exception):
    """Structured error → error envelope. `code` is stable, never translated."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http: int = 400,
        severity: str = "error",
        retryable: bool = False,
        action: str | None = None,
        message_key: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http = http
        self.severity = severity
        self.retryable = retryable
        self.action = action
        self.message_key = message_key
        self.details = details

    def body(self) -> dict:
        body: dict[str, Any] = {
            "code": self.code,
            "message": str(self),
            "severity": self.severity,
            "retryable": self.retryable,
        }
        if self.message_key:
            body["message_key"] = self.message_key
        if self.details:
            body["details"] = self.details
        if self.action:
            body["action"] = self.action
        return body


class SseResult:
    """Handler may return this to stream `events` then finish."""

    def __init__(self, events: Iterable[dict]) -> None:
        self.events = events


# ---------------------------------------------------------------------------
# request context / operations


@dataclass
class RequestContext:
    handler: PortalHandler
    params: dict[str, str]
    query: dict[str, list[str]]
    body: dict | None
    correlation_id: str

    def require(self, key: str) -> str:
        val = (self.body or {}).get(key)
        if val is None or not str(val).strip():
            raise PortalError(
                "PORTAL-MISSING-FIELD",
                f"required field '{key}' is missing",
                message_key="error.generic",
                details={"field": key},
            )
        return str(val)


@dataclass
class Operation:
    method: str
    path: str  # e.g. "/health" or "/tasks/{task_id}/events"
    handler: Callable[[RequestContext], Any]
    mutating: bool = False
    confirm: str | None = None  # literal required in body["confirm"]
    needs_plan_token: bool = False
    timeout: float = 30.0

    def match(self, path: str) -> dict[str, str] | None:
        want = self.path.split("/")
        got = path.split("/")
        if len(want) != len(got):
            return None
        params: dict[str, str] = {}
        for w, g in zip(want, got):
            if w.startswith("{") and w.endswith("}"):
                params[w[1:-1]] = g
            elif w != g:
                return None
        return params


@dataclass
class PortalAdapter:
    """Base adapter — a forge subclasses this (or constructs one via
    `register()`) to expose its real services. Every op maps to real
    service calls; nothing here fabricates state."""

    forge_id: str = "the-forge"
    forge_name: str = "Forge Portal"
    forge_version: str = "0.0.0"
    cli: str = "forge"
    theme: str = "the-forge"
    federated: bool = False
    assets_dir: Path | None = None
    workspace: str | None = None

    ops: list[Operation] = field(default_factory=list)

    def register(self, op: Operation) -> None:
        self.ops.append(op)

    # --- capability surface -------------------------------------------------
    def descriptor(self) -> dict:
        return {
            "forge_id": self.forge_id,
            "forge_name": self.forge_name,
            "forge_version": self.forge_version,
            "cli": self.cli,
            "theme": self.theme,
            "portal_version": portal_version(),
            "federated": self.federated,
            "capabilities": self.capabilities(),
            "nav": self.nav(),
            "workspace": {"root": self.workspace, "name": workspace_name(self.workspace)},
        }

    def capabilities(self) -> list[dict]:
        return []

    def nav(self) -> list[dict]:
        return []

    def health(self) -> dict:
        return {
            "state": "NOT_INSTALLED",
            "checks": [],
            "workspace": self.workspace,
            "profile": None,
            "updated_at": None,
        }


def portal_version() -> str:
    return "1.0.0"


def workspace_name(root: str | None) -> str | None:
    if not root:
        return None
    return Path(root).name or root


# ---------------------------------------------------------------------------
# forge-portal local presence — already-defined locations only:
#   FORGE_PORTAL_HOME env, ~/.forge/installations/forge-portal.json
#   (forge/InstallationManifest/v1 registry), ~/.forge/installs/forge-portal/.
# Never fabricates paths; every reported location exists on disk.


def detect_forge_portal() -> dict[str, Any]:
    """Whether a local forge-portal install exists in a defined location."""
    locations: list[dict[str, str]] = []

    env_root = os.environ.get("FORGE_PORTAL_HOME", "").strip()
    env_ok = bool(env_root) and Path(env_root).is_dir()
    if env_ok:
        locations.append({"kind": "env:FORGE_PORTAL_HOME", "path": env_root})

    home = Path(os.environ.get("FORGE_HOME_OVERRIDE") or Path.home())
    manifest_path = home / ".forge" / "installations" / "forge-portal.json"
    install_root: str | None = None
    installed_at: str | None = None
    manifest_ok = manifest_path.is_file()
    if manifest_ok:
        locations.append({"kind": "registry", "path": str(manifest_path)})
        try:
            doc = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                install_root = doc.get("install_root") or None
                installed_at = doc.get("installed_at") or None
        except (OSError, ValueError):
            pass  # unreadable manifest still proves a registered install

    if install_root and not Path(install_root).is_dir():
        install_root = None  # manifest points somewhere gone — honest
    if install_root:
        locations.append({"kind": "install_root", "path": install_root})
    elif not manifest_ok:
        default_root = home / ".forge" / "installs" / "forge-portal"
        if default_root.is_dir():
            install_root = str(default_root)
            locations.append({"kind": "install_root", "path": install_root})

    root = install_root or (env_root if env_ok else None)
    return {
        "state": "installed" if root or manifest_ok else "vendored",
        "install_root": root,
        "manifest": str(manifest_path) if manifest_ok else None,
        "installed_at": installed_at,
        "locations": locations,
    }


def _with_portal_presence(data: Any) -> Any:
    """Attach local forge-portal presence to health/status payloads."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    out["forge_portal"] = detect_forge_portal()
    return out


# ---------------------------------------------------------------------------
# plan tokens


def make_plan_token(secret: bytes, plan: dict) -> str:
    raw = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    sig = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    payload = f"{int(time.time())}:{hashlib.sha256(raw).hexdigest()[:16]}:{sig}"
    return secrets.token_urlsafe(8) + "." + urllib.parse.quote(payload, safe="")


def check_plan_token(secret: bytes, token: str, plan: dict, max_age_s: float = 900.0) -> bool:
    try:
        _nonce, payload = token.split(".", 1)
        ts_s, plan_hash, sig = urllib.parse.unquote(payload).split(":")
        ts = int(ts_s)
    except (ValueError, AttributeError):
        return False
    if time.time() - ts > max_age_s:
        return False
    raw = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    if hashlib.sha256(raw).hexdigest()[:16] != plan_hash:
        return False
    expected = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


# ---------------------------------------------------------------------------
# redaction


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _REDACT_EXEMPT:
                out[k] = v
            elif any(s in k.lower() for s in _SECRET_KEYS):
                out[k] = "«redacted»"
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# HTTP layer


class PortalHandler(BaseHTTPRequestHandler):
    server: PortalServer
    protocol_version = "HTTP/1.1"

    # silence per-request stderr logging — portal is a local tool
    def log_message(self, fmt: str, *args: Any) -> None:
        self.server.log(fmt % args if args else fmt)

    # -- envelope ----------------------------------------------------------
    def _send_json(self, status: int, payload: dict, *, extra_headers: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Cache-Control", "no-store")

    def _envelope(self, correlation: str, *, data: Any = None, error: dict | None = None) -> dict:
        env: dict[str, Any] = {"schema": SCHEMA, "correlation_id": correlation}
        if error is not None:
            env["error"] = error
        else:
            env["data"] = data
        return env

    # -- early rejection ---------------------------------------------------
    def _reject(self, status: int, payload: dict) -> None:
        """Send an error after draining any request body still on the wire.

        Responding without consuming the pending POST body leaves unread
        data in the socket; the kernel then resets the connection and the
        client never sees the response (WinError 10053 / ECONNRESET).
        Drain up to a hard ceiling, then close cleanly.
        """
        if self.command in ("POST", "PUT", "PATCH"):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            remaining = min(length, 8 << 20)
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 1 << 16))
                if not chunk:
                    break
                remaining -= len(chunk)
            self.close_connection = True
            self._send_json(status, payload, extra_headers={"Connection": "close"})
            return
        self._send_json(status, payload)

    # -- session -----------------------------------------------------------
    def _session_ok(self) -> bool:
        token = self.headers.get(SESSION_HEADER)
        if not token or not hmac.compare_digest(token, self.server.session_token):
            return False
        cookie = self.headers.get("Cookie") or ""
        if SESSION_COOKIE in cookie:
            jar = dict(p.strip().split("=", 1) for p in cookie.split(";") if "=" in p)
            cval = jar.get(SESSION_COOKIE, "")
            if cval and not hmac.compare_digest(cval, self.server.session_token):
                return False
        return True

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True  # non-browser client (curl) — session header still required
        host = urllib.parse.urlparse(origin).hostname or ""
        return host in ("127.0.0.1", "localhost", "::1")

    def _host_ok(self) -> bool:
        # DNS-rebinding guard: even with a valid session/origin, a browser
        # pointed at attacker.example resolved to 127.0.0.1 must not reach
        # the API or the assets — refuse any non-loopback Host early.
        raw = (self.headers.get("Host") or "").strip().lower()
        if raw.startswith("["):
            host = raw[1:].split("]")[0]
        else:
            host = raw.split(":")[0]
        return host in ("127.0.0.1", "localhost", "::1")

    # -- routing -----------------------------------------------------------
    def do_GET(self) -> None:
        if not self._host_ok():
            self._reject(403, self._envelope(self._cid(), error=_err("PORTAL-HOST", "host must be loopback")))
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith(API_PREFIX + "/"):
            self._api("GET", path, parsed)
        else:
            self._static(path, parsed)

    def do_POST(self) -> None:
        if not self._host_ok():
            self._reject(403, self._envelope(self._cid(), error=_err("PORTAL-HOST", "host must be loopback")))
            return
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith(API_PREFIX + "/"):
            self._reject(404, self._envelope(self._cid(), error=_err("PORTAL-NOT-FOUND", "not found")))
            return
        self._api("POST", parsed.path, parsed)

    # -- api ---------------------------------------------------------------
    def _cid(self) -> str:
        return self.headers.get("X-Correlation-Id") or secrets.token_hex(6)

    def _api(self, method: str, path: str, parsed: urllib.parse.ParseResult) -> None:
        cid = self._cid()
        rel = path[len(API_PREFIX):] or "/"

        if not self._session_ok():
            self._reject(
                403,
                self._envelope(
                    cid,
                    error=_err("PORTAL-SESSION", "missing or invalid session", message_key="error.session"),
                ),
            )
            return

        op = self._find_op(method, rel)
        if op is None:
            self._send_json(404, self._envelope(cid, error=_err("PORTAL-NOT-FOUND", f"no such operation: {rel}")))
            return
        params = op[1]
        operation = op[0]

        if method == "POST":
            if not self._origin_ok():
                self._reject(
                    403,
                    self._envelope(cid, error=_err("PORTAL-ORIGIN", "cross-origin request refused")),
                )
                return
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if ctype != "application/json":
                self._reject(
                    415,
                    self._envelope(cid, error=_err("PORTAL-CONTENT-TYPE", "Content-Type must be application/json")),
                )
                return
            if operation.mutating and not self.server.rate_limiter.allow():
                self._reject(
                    429,
                    self._envelope(
                        cid,
                        error=_err("PORTAL-RATE-LIMITED", "too many mutating requests", retryable=True),
                    ),
                )
                return

        body = None
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._reject(
                    413,
                    self._envelope(cid, error=_err("PORTAL-PAYLOAD-TOO-LARGE", "body exceeds 1 MiB")),
                )
                return
            raw = self.rfile.read(length) if length else b"{}"
            try:
                parsed_body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._send_json(400, self._envelope(cid, error=_err("PORTAL-BAD-JSON", "body is not valid JSON")))
                return
            if not isinstance(parsed_body, dict):
                self._send_json(400, self._envelope(cid, error=_err("PORTAL-BAD-JSON", "body must be a JSON object")))
                return
            body = parsed_body
            if operation.confirm is not None and body.get("confirm") != operation.confirm:
                self._send_json(
                    400,
                    self._envelope(
                        cid,
                        error=_err(
                            "PORTAL-CONFIRM",
                            f'operation requires confirm: "{operation.confirm}"',
                            details={"expected": operation.confirm},
                        ),
                    ),
                )
                return
            if operation.needs_plan_token and not body.get("plan_token"):
                self._send_json(
                    400,
                    self._envelope(cid, error=_err("PORTAL-PLAN-REQUIRED", "plan_token is required")),
                )
                return

        ctx = RequestContext(
            handler=self,
            params=params,
            query=urllib.parse.parse_qs(parsed.query),
            body=body,
            correlation_id=cid,
        )

        try:
            result = self.server.run_with_timeout(operation.handler, ctx, operation.timeout)
        except PortalError as e:
            self._send_json(e.http, self._envelope(cid, error=e.body()))
            return
        except TimeoutError:
            self._send_json(
                504,
                self._envelope(
                    cid,
                    error=_err("PORTAL-TIMEOUT", f"operation exceeded {operation.timeout:.0f}s", retryable=True),
                ),
            )
            return
        except Exception as e:  # noqa: BLE001 — outermost boundary; never leak internals
            self.server.log(f"handler error on {rel}: {type(e).__name__}")
            self._send_json(
                500,
                self._envelope(
                    cid,
                    error=_err("PORTAL-INTERNAL", "internal error", retryable=False),
                ),
            )
            return

        if isinstance(result, SseResult):
            self._stream_sse(result, cid)
            return
        self._send_json(200, self._envelope(cid, data=redact(result)))

    def _find_op(self, method: str, rel: str) -> tuple[Operation, dict[str, str]] | None:
        for op in self.server.adapter.ops:
            if op.method != method:
                continue
            params = op.match(rel)
            if params is not None:
                return op, params
        return None

    def _stream_sse(self, result: SseResult, cid: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self._security_headers()
        self.end_headers()
        try:
            for event in result.events:
                payload = json.dumps(redact(event), ensure_ascii=False)
                self.wfile.write(f"data: {payload}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            self.server.log("sse client disconnected")

    # -- static ------------------------------------------------------------
    def _static(self, path: str, parsed: urllib.parse.ParseResult) -> None:
        assets = self.server.adapter.assets_dir
        if assets is None:
            self.send_error(404)
            return
        url_q = urllib.parse.parse_qs(parsed.query)
        session_ok = url_q.get("forge_session", [""])[0] == self.server.session_token

        rel = urllib.parse.unquote(path).lstrip("/")
        # normalize — traversal refuses hard
        norm = str(Path(rel))
        if norm.startswith(("..", "/")) or ".." in Path(rel).parts:
            self.send_error(404)
            return
        target = (assets / norm).resolve()
        try:
            target.relative_to(assets.resolve())
        except ValueError:
            self.send_error(404)
            return

        if not target.is_file():
            # SPA fallback: any extension-less path serves index.html
            index = assets / "index.html"
            if index.is_file() and "." not in Path(rel).name:
                target = index
            else:
                self.send_error(404)
                return

        ctype = _content_type(target)
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self._security_headers()
        if session_ok:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={self.server.session_token}; SameSite=Strict; HttpOnly; Path=/",
            )
        self.end_headers()
        self.wfile.write(data)


def _err(code: str, message: str, *, retryable: bool = False, message_key: str | None = None, details: dict | None = None) -> dict:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "severity": "error",
        "retryable": retryable,
    }
    if message_key:
        body["message_key"] = message_key
    if details:
        body["details"] = details
    return body


_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".map": "application/json",
    ".txt": "text/plain; charset=utf-8",
}


def _content_type(path: Path) -> str:
    return _TYPES.get(path.suffix.lower(), "application/octet-stream")


# ---------------------------------------------------------------------------
# rate limiter


class RateLimiter:
    def __init__(self, limit: int = MUTATION_LIMIT, window: float = MUTATION_WINDOW_S) -> None:
        self.limit = limit
        self.window = window
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._hits and now - self._hits[0] > self.window:
                self._hits.popleft()
            if len(self._hits) >= self.limit:
                return False
            self._hits.append(now)
            return True


# ---------------------------------------------------------------------------
# server


class PortalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        adapter: PortalAdapter,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        quiet: bool = True,
    ) -> None:
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("portal binds loopback only")
        self.adapter = adapter
        self.session_token = secrets.token_urlsafe(24)
        self._plan_secret = secrets.token_bytes(32)
        self.rate_limiter = RateLimiter()
        self._quiet = quiet
        self._executor = __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="forge-portal"
        )
        super().__init__((host, port), PortalHandler)

    # -- helpers used by the handler --------------------------------------
    def log(self, msg: str) -> None:
        if not self._quiet:
            print(f"[forge-portal] {msg}")

    def run_with_timeout(self, fn: Callable[[RequestContext], Any], ctx: RequestContext, timeout: float) -> Any:
        fut = self._executor.submit(fn, ctx)
        return fut.result(timeout=timeout)

    def sign_plan(self, plan: dict) -> str:
        return make_plan_token(self._plan_secret, plan)

    def check_plan(self, token: str, plan: dict) -> bool:
        return check_plan_token(self._plan_secret, token, plan)

    # -- public API ---------------------------------------------------------
    @property
    def port(self) -> int:
        return self.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?forge_session={self.session_token}"

    def serve_in_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.serve_forever, name="forge-portal-http", daemon=True)
        t.start()
        return t


def default_operations(adapter: PortalAdapter) -> list[Operation]:
    """Core read-only surface every portal gets for free, mapped to
    adapter methods. Forges add mutating + domain ops on top."""

    def _get(attr: str, fallback: Any):
        fn = getattr(adapter, attr, None) or fallback

        def h(ctx: RequestContext) -> Any:
            if fn is None:
                raise PortalError("PORTAL-UNSUPPORTED", f"capability '{attr}' not available on this forge", http=404)
            return fn(ctx) if _wants_ctx(fn) else fn()

        return h

    return [
        Operation(
            "GET",
            "/bootstrap",
            lambda ctx: {
                "descriptor": adapter.descriptor(),
                "health": _with_portal_presence(adapter.health()),
            },
        ),
        Operation("GET", "/health", _presence_op(_get("health", None))),
        Operation("GET", "/capabilities", lambda ctx: adapter.capabilities()),
        Operation(
            "GET",
            "/installation/status",
            _presence_op(_get("installation_status", adapter.health)),
        ),
    ]


def _presence_op(handler: Callable[[RequestContext], Any]) -> Callable[[RequestContext], Any]:
    def h(ctx: RequestContext) -> Any:
        return _with_portal_presence(handler(ctx))

    return h


def _wants_ctx(fn: Callable) -> bool:
    try:
        import inspect

        return len(inspect.signature(fn).parameters) >= 1
    except (TypeError, ValueError):
        return False


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def serve(adapter: PortalAdapter, *, port: int = 0, open_url: bool = True, quiet: bool = True) -> None:
    """Blocking entry point used by `<cli> portal`."""
    server = PortalServer(adapter, port=port, quiet=quiet)
    url = server.url
    print(f"forge-portal listening at {url}")
    if open_url:
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception as e:  # noqa: BLE001 — browser open is best-effort
            print(f"could not open browser: {e}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":  # manual smoke: python forge_portal.py
    serve(PortalAdapter(), quiet=False)
