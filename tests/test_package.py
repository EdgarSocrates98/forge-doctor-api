from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import forge_doctor_api

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "forge_doctor_api"
# Vendored upstream surfaces (byte-parity with the-forge): sanctioned host
# imports (loopback Studio, terminal kit) — audited upstream, exempt here.
_VENDORED = frozenset({
    "_graphstudio.py",
    "ui/i18n.py", "ui/kit.py", "ui/wizard.py", "ui/home.py",
})


def load_pyproject() -> dict[str, object]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_project_metadata() -> None:
    project = load_pyproject()["project"]
    assert isinstance(project, dict)
    assert project["name"] == "forge-doctor-api"
    assert project["version"] == "0.2.0" == forge_doctor_api.__version__
    assert project["requires-python"] == ">=3.11"
    assert project["scripts"] == {"forge-doctor-api": "forge_doctor_api.cli:main"}


def test_runtime_dependencies_limited_to_typer_rich_and_pyyaml() -> None:
    project = load_pyproject()["project"]
    assert isinstance(project, dict)
    names = sorted(dep.split(">")[0].split("=")[0].split("[")[0] for dep in project["dependencies"])
    # pyyaml: OpenAPI YAML parsing (spec 004); the only runtime dep beyond the CLI stack.
    assert names == ["pyyaml", "rich", "typer"]


def test_dev_dependencies() -> None:
    poetry = load_pyproject()["tool"]["poetry"]  # type: ignore[index]
    assert set(poetry["group"]["dev"]["dependencies"]) == {"pytest", "ruff", "mypy", "types-PyYAML"}


def test_directory_layout() -> None:
    for name in ("analyzers", "checks", "core", "cli", "integrations", "output", "plugins"):
        assert (PACKAGE / name / "__init__.py").is_file(), name
    for name in ("sdk.py", "core/models.py", "core/context.py"):
        assert (PACKAGE / name).is_file(), name


FORBIDDEN_IMPORTS = {"socket", "urllib", "http", "requests", "httpx", "subprocess"}


def test_no_network_or_process_imports() -> None:
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.relative_to(PACKAGE).as_posix() in _VENDORED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.split(".")[0]}
            else:
                continue
            assert not roots & FORBIDDEN_IMPORTS, f"{path}: {roots & FORBIDDEN_IMPORTS}"


def test_host_access_only_through_context() -> None:
    forbidden = ("os.environ", "Path.cwd", "os.getcwd", "datetime.now", "datetime.utcnow", "open(")
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == PACKAGE / "core" / "context.py":
            continue
        if path.relative_to(PACKAGE).as_posix() in _VENDORED:
            continue
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{path}: {needle}"
