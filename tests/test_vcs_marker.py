"""Regression: stray forge.json in an ancestor must not mark a project root."""

import tempfile

from pathlib import Path

from forge_doctor_api.ui import wizard


def test_stray_forge_json_ancestor_is_not_a_root() -> None:
    root = Path(tempfile.mkdtemp())
    (root / "forge.json").write_text("{}")
    inner = root / "a" / "b"
    inner.mkdir(parents=True)
    assert not wizard._has_vcs_root(inner)


def test_forge_json_with_pyproject_is_a_root(tmp_path: Path) -> None:
    (tmp_path / "forge.json").write_text("{}")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    inner = tmp_path / "sub"
    inner.mkdir()
    assert wizard._has_vcs_root(inner)


def test_git_alone_is_a_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    inner = tmp_path / "sub"
    inner.mkdir()
    assert wizard._has_vcs_root(inner)
