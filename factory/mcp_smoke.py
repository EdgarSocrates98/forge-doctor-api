"""Spec 083 — MCP stdio smoke against an *installed* executable.

Spawns `forge-doctor-api mcp <fixture-dir>` as a real subprocess and
speaks newline-delimited JSON-RPC over its stdio transport:

    initialize → notifications/initialized → tools/list → tools/call

Asserts the protocol handshake, the frozen tool inventory, and a
live `doctor.get_service` round trip. Exits non-zero on any failure.
Used by CI's wheel-install smoke to prove the shipped artifact serves
the MCP boundary — not just the source tree.

Run:  python factory/mcp_smoke.py [fixture-dir] [--exe PATH]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from queue import Empty, Queue

ROOT = Path(__file__).resolve().parents[1]
TOOL_COUNT = 17
_TIMEOUT = 60

_FIXTURE = (
    'openapi: 3.0.3\n'
    'info: {title: Smoke, version: "1"}\n'
    'paths:\n'
    '  /pets:\n'
    '    get:\n'
    '      operationId: listPets\n'
    '      responses: {"200": {description: ok}}\n')


def _reader(stream: object, out: Queue[str]) -> None:
    for line in iter(stream.readline, ""):  # type: ignore[attr-defined]
        out.put(line)


def _readline(out: Queue[str], label: str) -> dict:
    try:
        line = out.get(timeout=_TIMEOUT)
    except Empty:
        raise SystemExit(
            f"mcp_smoke: timed out waiting for {label}") from None
    return json.loads(line)


def smoke(exe: str | None, fixture: Path) -> dict:
    cmd = [exe] if exe else [sys.executable, "-m", "forge_doctor_api"]
    proc = subprocess.Popen(
        [*cmd, "mcp", str(fixture)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    assert proc.stdin and proc.stdout
    lines: Queue[str] = Queue()
    threading.Thread(target=_reader, args=(proc.stdout, lines),
                     daemon=True).start()

    def send(msg: dict) -> None:
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-11-25",
                         "capabilities": {},
                         "clientInfo": {"name": "mcp-smoke",
                                        "version": "0"}}})
        init = _readline(lines, "initialize")
        assert "result" in init, f"initialize failed: {init}"
        send({"jsonrpc": "2.0",
              "method": "notifications/initialized"})

        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = _readline(lines, "tools/list")
        names = sorted(t["name"] for t in tools["result"]["tools"])
        assert len(names) == TOOL_COUNT, f"tool inventory: {names}"

        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "doctor.get_service", "arguments": {}}})
        call = _readline(lines, "doctor.get_service")
        result = call["result"]
        assert result.get("isError") is not True, f"tool error: {result}"
        payload = json.loads(result["content"][0]["text"])
        assert isinstance(payload, dict)
        return {"tools": names, "service": payload}
    finally:
        proc.kill()
        proc.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", nargs="?", type=Path, default=None)
    parser.add_argument("--exe", default=None,
                        help="installed console script; default: "
                             "`python -m forge_doctor_api`")
    args = parser.parse_args()
    if args.fixture:
        report = smoke(args.exe, args.fixture)
    else:
        with tempfile.TemporaryDirectory() as td:
            fixture = Path(td)
            (fixture / "api.yaml").write_text(_FIXTURE, encoding="utf-8")
            report = smoke(args.exe, fixture)
    print(f"mcp_smoke: OK — {len(report['tools'])} tools over stdio, "
          f"doctor.get_service answered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
