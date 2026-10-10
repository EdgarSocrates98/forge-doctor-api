"""Spec 030 — wheel/sdist build proofs and metadata (§182)."""

from __future__ import annotations

import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import forge_doctor_api

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict[str, object]:
    return tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_python_support_declared() -> None:
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    assert project["requires-python"] == ">=3.11"
    classifiers = project.get("classifiers") or []
    for minor in ("3.11", "3.12", "3.13"):
        assert any(f"Python :: {minor}" in str(c) for c in classifiers), minor


def test_no_forbidden_runtime_imports() -> None:
    """Portability: no os-specific or network imports in the package."""
    import ast
    forbidden = {"socket", "urllib", "requests", "httpx", "subprocess",
                 "winreg", "msvcrt", "fcntl", "termios"}
    vendored = {"_graphstudio.py",
                "ui/i18n.py", "ui/kit.py", "ui/wizard.py", "ui/home.py",
                "ui/app.py", "ui/screen.py", "ui/tui.py"}
    pkg = ROOT / "src" / "forge_doctor_api"
    for path in sorted(pkg.rglob("*.py")):
        if path.relative_to(pkg).as_posix() in vendored:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                mods = {(node.module or "").split(".")[0]}
            else:
                continue
            bad = mods & forbidden
            assert not bad, f"{path.name}: {bad}"


def _build(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    cmd = [sys.executable, "-m", "build", "--outdir", str(dist)]
    try:
        subprocess.run(
            [*cmd, "--wheel", "--sdist"], cwd=ROOT,
            check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "wheel", str(ROOT),
                 "--no-deps", "-w", str(dist)],
                check=True, capture_output=True, text=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            # pip-less environments (uv venvs): `uv build` emits both the
            # sdist and the wheel with no build module required.
            subprocess.run(
                ["uv", "build", "--out-dir", str(dist)],
                cwd=ROOT, check=True, capture_output=True, text=True)
    return dist


def test_wheel_and_sdist_contents(tmp_path: Path) -> None:
    dist = _build(tmp_path)
    wheels = list(dist.glob("*.whl"))
    assert wheels, "wheel not built"
    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
    # knowledge packs ship inside the wheel
    assert any(n.startswith("forge_doctor_api/knowledge/")
               and n.endswith(".yaml") for n in names)
    assert any(n.endswith("cli/__init__.py") for n in names)
    meta = next(n for n in names if n.endswith("METADATA"))
    with zipfile.ZipFile(wheels[0]) as zf:
        text = zf.read(meta).decode()
    assert "Requires-Python: >=3.11" in text
    assert f"Version: {forge_doctor_api.__version__}" in text

    sdists = list(dist.glob("*.tar.gz"))
    if sdists:  # pip-wheel fallback produces no sdist
        with tarfile.open(sdists[0]) as tf:
            sdist_names = tf.getnames()
        assert any("pyproject.toml" in n for n in sdist_names)
        assert any("knowledge" in n and n.endswith(".yaml")
                   for n in sdist_names)
