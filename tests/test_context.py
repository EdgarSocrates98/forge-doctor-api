from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from forge_doctor_api.core.context import ContextError, ProjectContext


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "svc" / "api").mkdir(parents=True)
    (tmp_path / "svc" / "api" / "openapi.yaml").write_text("openapi: 3.1.0\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    return tmp_path


def test_from_root_resolves_and_sorts_workspaces(project: Path) -> None:
    ctx = ProjectContext.from_root(project, workspace_paths=("svc/api", "svc", "svc"))
    assert ctx.root == project.resolve()
    assert ctx.workspace_paths == ("svc", "svc/api")


def test_from_root_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(ContextError):
        ProjectContext.from_root(tmp_path / "missing")


def test_from_root_rejects_missing_workspace(project: Path) -> None:
    with pytest.raises(ContextError):
        ProjectContext.from_root(project, workspace_paths=("nope",))


def test_read_text_and_exists(project: Path) -> None:
    ctx = ProjectContext.from_root(project)
    assert ctx.exists("svc/api/openapi.yaml")
    assert ctx.read_text("svc\\api\\openapi.yaml") == "openapi: 3.1.0\n"
    assert not ctx.exists("missing.txt")


@pytest.mark.parametrize("bad", ["../outside.txt", "svc/../../x", "/etc/passwd", "C:/Windows"])
def test_paths_cannot_escape_root(project: Path, bad: str) -> None:
    ctx = ProjectContext.from_root(project)
    with pytest.raises(ContextError):
        ctx.resolve(bad)


def test_relative_is_posix_and_bounded(
    project: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    ctx = ProjectContext.from_root(project)
    assert ctx.relative(project / "svc" / "api" / "openapi.yaml") == "svc/api/openapi.yaml"
    assert ctx.relative(project) == "."
    with pytest.raises(ContextError):
        ctx.relative(tmp_path_factory.mktemp("elsewhere"))


def test_iter_files_is_sorted_and_relative(project: Path) -> None:
    ctx = ProjectContext.from_root(project)
    assert list(ctx.iter_files()) == ["a.txt", "b.txt", "svc/api/openapi.yaml"]
    assert list(ctx.iter_files("**/*.yaml")) == ["svc/api/openapi.yaml"]


def test_iter_files_is_deterministic(project: Path) -> None:
    ctx = ProjectContext.from_root(project)
    assert list(ctx.iter_files()) == list(ctx.iter_files())


def test_now_requires_injected_clock(project: Path) -> None:
    with pytest.raises(ContextError, match="no clock"):
        ProjectContext.from_root(project).now()


def test_now_uses_injected_clock(project: Path) -> None:
    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    assert ProjectContext.from_root(project, clock=lambda: fixed).now() == fixed


def test_now_rejects_naive_clock(project: Path) -> None:
    ctx = ProjectContext.from_root(project, clock=lambda: datetime(2026, 1, 1))  # noqa: DTZ001
    with pytest.raises(ContextError, match="timezone-aware"):
        ctx.now()
