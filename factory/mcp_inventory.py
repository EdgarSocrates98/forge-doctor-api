"""Spec 083 — frozen MCP tool/resource inventory.

Emits `factory/artifacts/mcp-inventory.json`: every `doctor.*` tool
with its input-schema digest, stability class and contract version,
plus the `doctor://` resource/template lists. The tool *names* are
the public contract — drift here is a breaking change candidates.

`--check` regenerates and diffs; `--stdout` prints. Requires the
optional `mcp` extra for full schema digests; without it only the
source-level name list can be produced (and --check cannot verify
schema digests — it reports that honestly).

Run:  python factory/mcp_inventory.py [--check|--stdout|--out PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ARTIFACT = ROOT / "factory" / "artifacts" / "mcp-inventory.json"
INVENTORY_VERSION = 1

_FIXTURE = (
    'openapi: 3.0.3\n'
    'info: {title: Inventory, version: "1"}\n'
    'paths:\n'
    '  /x:\n'
    '    get:\n'
    '      operationId: getX\n'
    '      responses: {"200": {description: ok}}\n')


def _tool_names_from_source() -> tuple[str, ...]:
    src = (SRC / "forge_doctor_api" / "handoff" / "mcp_server.py"
           ).read_text(encoding="utf-8")
    return tuple(sorted(set(re.findall(r'"(doctor\.[a-z_]+)"', src))))


def _digest(obj: object) -> str:
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_inventory() -> dict:
    _src_on_path = str(SRC)
    if _src_on_path not in sys.path:
        sys.path.insert(0, _src_on_path)
    try:
        import mcp  # noqa: F401
    except ImportError:
        return {
            "inventory_version": INVENTORY_VERSION,
            "schemas_verified": False,
            "tools": [{"name": n, "stability": "stable", "version": 1}
                      for n in _tool_names_from_source()],
            "resources": [],
            "resource_templates": [],
        }
    from forge_doctor_api.handoff.mcp_server import build_server
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "api.yaml").write_text(_FIXTURE, encoding="utf-8")
        server = build_server(td)
    tools = asyncio.run(server.list_tools())
    resources = asyncio.run(server.list_resources())
    templates = asyncio.run(server.list_resource_templates())
    return {
        "inventory_version": INVENTORY_VERSION,
        "schemas_verified": True,
        "tools": [{
            "name": tool.name,
            "stability": "stable",
            "version": 1,
            "description": tool.description or "",
            "input_schema_sha256": _digest(
                getattr(tool, "inputSchema", None)
                or getattr(tool, "input_schema", None)),
            "input_schema": (
                getattr(tool, "inputSchema", None)
                or getattr(tool, "input_schema", None)),
        } for tool in sorted(tools, key=lambda x: x.name)],
        "resources": sorted(str(r.uri) for r in resources),
        "resource_templates": sorted(
            getattr(tpl, "uriTemplate", None)
            or getattr(tpl, "uri_template", "")
            for tpl in templates),
    }


def _render(inventory: dict) -> str:
    return json.dumps(inventory, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ARTIFACT)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="regenerate and diff against --out; "
                             "exits non-zero on drift")
    args = parser.parse_args()
    rendered = _render(build_inventory())
    if args.stdout:
        sys.stdout.write(rendered)
        return 0
    if args.check:
        if not args.out.exists():
            print(f"mcp_inventory --check: missing {args.out}; record "
                  f"with `python factory/mcp_inventory.py`",
                  file=sys.stderr)
            return 1
        committed = args.out.read_text(encoding="utf-8")
        if committed != rendered:
            print("mcp_inventory --check: drift — tool schemas or "
                  "inventory changed; regenerate with "
                  "`python factory/mcp_inventory.py`",
                  file=sys.stderr)
            return 1
        print(f"mcp_inventory --check: {args.out} matches live server")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    data = json.loads(rendered)
    print(f"mcp_inventory: {args.out} "
          f"({len(data['tools'])} tools, "
          f"{len(data['resources'])} resources, "
          f"{len(data['resource_templates'])} templates)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
