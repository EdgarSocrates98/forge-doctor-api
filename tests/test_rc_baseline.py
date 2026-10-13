"""RC baseline artifact (spec 081): schema, check-mode, determinism."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import forge_doctor_api

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "docs" / "rc-baseline.json"
GENERATOR = ROOT / "factory" / "rc_baseline.py"

REQUIRED_KEYS = {
    "baseline_version",
    "version",
    "python_requires",
    "python_classified",
    "cli_command_count",
    "cli_commands",
    "mcp_tool_count",
    "mcp_tools",
    "contract_version",
    "contract_schema_ids",
    "forge_protocol_version",
    "lab_scenario_count",
    "oss_slice_count",
    "oss_negative_count",
    "test_file_count",
    "scale_check_scales",
    "scale_headroom",
    "sbom_dependency_count",
    "runtime_dependencies",
    "optional_extras",
}


def _load() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_baseline_file_exists_and_has_pinned_keys() -> None:
    assert BASELINE.is_file(), "docs/rc-baseline.json must be committed"
    data = _load()
    missing = REQUIRED_KEYS - set(data)
    assert not missing, f"baseline missing keys: {sorted(missing)}"


def test_baseline_counts_match_reality() -> None:
    data = _load()
    assert data["version"] == forge_doctor_api.__version__
    assert data["cli_command_count"] == len(data["cli_commands"])
    assert data["mcp_tool_count"] == len(data["mcp_tools"])
    assert data["cli_command_count"] > 0
    assert data["mcp_tool_count"] > 0
    assert data["contract_version"] == "forge-contracts/1"
    assert isinstance(data["test_file_count"], int)
    assert data["test_file_count"] > 0


def test_baseline_check_mode_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, (
        f"rc_baseline --check failed:\n{result.stdout}\n{result.stderr}")


def test_baseline_generation_is_deterministic() -> None:
    runs: list[bytes] = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--stdout"],
            capture_output=True, cwd=ROOT,
        )
        assert result.returncode == 0
        runs.append(result.stdout)
    assert runs[0] == runs[1], "baseline output must be byte-identical"


def test_rc_policy_and_public_surface_docs_exist() -> None:
    policy = (ROOT / "docs" / "rc-policy.md").read_text(encoding="utf-8")
    surface = (ROOT / "docs" / "public-surface.md").read_text(
        encoding="utf-8")
    for cls in ("STABLE", "WIRE", "UX", "EXPERIMENTAL", "INTERNAL",
                "DEPRECATED"):
        assert cls in policy, f"rc-policy.md missing class {cls}"
    for section in ("CLI", "SDK", "MCP", "contract", "check", "plugin"):
        assert section.lower() in surface.lower(), (
            f"public-surface.md missing {section} section")
