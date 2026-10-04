"""Spec 069 — CycloneDX 1.5 SBOM for release artifacts.

Generated from `pyproject.toml` declarations only: runtime
`[project.dependencies]` become `required` components, each
`[project.optional-dependencies]` extra becomes `optional` components.
No transitive or undeclared dependency is ever claimed — this SBOM
states exactly what the package metadata states.

Run:  python factory/sbom.py [--out dist/sbom.cdx.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_VERSION = "1.5"

_REQ_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)\s*(?P<extra>\[[^\]]*\])?\s*"
    r"(?P<spec>[^;]*)?(?:;.*)?$")


def _parse_requirement(req: str) -> dict[str, str]:
    match = _REQ_RE.match(req.strip())
    if not match:
        return {"name": req.strip(), "spec": ""}
    return {
        "name": match.group("name"),
        "spec": (match.group("spec") or "").strip(),
    }


def _component(name: str, spec: str, scope: str,
               extra_of: str | None = None) -> dict[str, object]:
    purl = f"pkg:pypi/{name.lower().replace('_', '-')}"
    if spec:
        purl += f"@{spec.lstrip('=<>!~ ').split(',')[0]}"
    comp: dict[str, object] = {
        "type": "library",
        "bom-ref": purl,
        "name": name,
        "scope": scope,
        "purl": purl,
    }
    if spec:
        comp["version"] = spec
    if extra_of is not None:
        comp["properties"] = [{"name": "optional-extra",
                               "value": extra_of}]
    return comp


def build_sbom(pyproject: Path | None = None) -> dict[str, object]:
    data = tomllib.loads(
        (pyproject or ROOT / "pyproject.toml").read_text("utf-8"))
    project = data["project"]
    components: list[dict[str, object]] = []
    for req in project.get("dependencies", []):
        parsed = _parse_requirement(req)
        components.append(
            _component(parsed["name"], parsed["spec"], "required"))
    for extra, reqs in sorted(
            project.get("optional-dependencies", {}).items()):
        for req in reqs:
            parsed = _parse_requirement(req)
            components.append(_component(
                parsed["name"], parsed["spec"], "optional", extra))
    name = project["name"]
    version = project["version"]
    return {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": f"pkg:pypi/{name}@{version}",
                "name": name,
                "version": version,
                "description": project.get("description", ""),
                "licenses": [],
            },
            "tools": [{
                "vendor": "forge-doctor-api",
                "name": "factory/sbom.py",
            }],
        },
        "components": components,
        "dependencies": [{
            "ref": f"pkg:pypi/{name}@{version}",
            "dependsOn": [c["bom-ref"] for c in components],
        }],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path,
                        default=ROOT / "dist" / "sbom.cdx.json")
    args = parser.parse_args()
    sbom = build_sbom()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(sbom, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"sbom: {args.out} ({len(sbom['components'])} components)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
