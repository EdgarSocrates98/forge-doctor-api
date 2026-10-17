"""Docs-as-code gate (Forge Knowledge Program §18): no broken internal links
in active documentation.

Historical/frozen trees are exempt — they are preserved, not repaired:
``docs/sdd/archive``, ``docs/superpowers/plans``, ``docs/historico``,
``.claude/sdd/archive``, ``.agents/sdd/archive``, ``vendor/``. A broken link
inside an active doc fails the gate; the inventory reports name the file.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXEMPT_PREFIXES = (
    "docs/sdd/archive/", "docs/superpowers/", "docs/historico/",
    ".claude/sdd/", ".agents/sdd/", ".devin/sdd/", "vendor/",
    "docs/reports/", "docs/knowledge-program/", "knowledge/devin/",
)


def _load_manifest():
    spec = importlib.util.spec_from_file_location(
        "doc_manifest", ROOT / "scripts" / "docs" / "doc_manifest.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("cli,forge", [
    # overridden per repo by edit below — single binding keeps vendoring simple
    ("forge-doctor-api", "forge-doctor-api"),
])
def test_no_broken_links_in_active_docs(cli: str, forge: str):
    mod = _load_manifest()
    inv = ROOT / "docs" / "knowledge-program" / "inventory.jsonl"
    if not inv.exists():
        pytest.skip("run scripts/docs/doc_manifest.py first")
    rows = [json.loads(line) for line in inv.read_text("utf-8").splitlines()]
    broken: list[dict] = []
    for r in rows:
        path = r["path"]
        if path.startswith(EXEMPT_PREFIXES):
            continue
        if "VENDORED_UPSTREAM" in r["secondary"]:
            continue
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        links, _ = mod._links_and_anchors(text)
        broken += mod._check_links(ROOT, Path(path), links)
    assert not broken, "broken internal links in active docs:\n" + "\n".join(
        f"  {b['file']} -> {b['link']} ({b['problem']})" for b in broken[:30]
    )


class TestRepoUrlResolver:
    """Tag-pinned self-repo URLs resolve as repo paths for the link gate
    (cycle-10.3 review): nested docs, slash-refs, query strings, escapes.
    """

    SLUG = "Org/proj"
    BASE = "https://github.com/Org/proj"

    @pytest.fixture()
    def repo(self, tmp_path: Path) -> Path:
        (tmp_path / "pyproject.toml").write_text(
            f'[project.urls]\nRepository = "{self.BASE}"\n', encoding="utf-8"
        )
        (tmp_path / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
        return tmp_path

    def test_nested_doc_link_resolves_against_repo_root(self, repo: Path) -> None:
        mod = _load_manifest()
        found = mod._check_links(
            repo,
            Path("docs/guia/README.md"),
            [f"{self.BASE}/blob/v1.0/AGENTS.md"],
        )
        assert found == []

    def test_broken_repo_url_is_reported(self, repo: Path) -> None:
        mod = _load_manifest()
        found = mod._check_links(
            repo,
            Path("docs/guia/README.md"),
            [f"{self.BASE}/blob/v1.0/MISSING.md"],
        )
        assert [f["problem"] for f in found] == ["broken internal link"]

    def test_slash_containing_ref(self, repo: Path) -> None:
        mod = _load_manifest()
        url = f"{self.BASE}/blob/release/1.0/AGENTS.md"
        assert mod._repo_url_path(url, self.SLUG, repo) == "AGENTS.md"
        assert mod._check_links(repo, Path("docs/guia/README.md"), [url]) == []

    def test_query_string_and_fragment_are_stripped(self, repo: Path) -> None:
        mod = _load_manifest()
        url = f"{self.BASE}/blob/v1.0/AGENTS.md?plain=1#L10"
        assert mod._repo_url_path(url, self.SLUG, repo) == "AGENTS.md"

    def test_dotdot_inside_url_is_not_a_blob_ref(self, repo: Path) -> None:
        mod = _load_manifest()
        url = f"{self.BASE}/blob/v1.0/../AGENTS.md"
        assert mod._repo_url_path(url, self.SLUG, repo) is None

    def test_dotdot_escape_is_rejected(self, repo: Path) -> None:
        mod = _load_manifest()
        url = f"{self.BASE}/blob/v1.0/../../outside.md"
        assert mod._repo_url_path(url, self.SLUG, repo) is None

    def test_foreign_slug_is_not_mapped(self, repo: Path) -> None:
        mod = _load_manifest()
        url = "https://github.com/Other/repo/blob/v1.0/AGENTS.md"
        assert mod._repo_url_path(url, self.SLUG, repo) is None
        assert mod._check_links(repo, Path("docs/guia/README.md"), [url]) == []

    def test_mapped_url_missing_anchor_is_reported(self, repo: Path) -> None:
        mod = _load_manifest()
        found = mod._check_links(
            repo,
            Path("docs/guia/README.md"),
            [f"{self.BASE}/blob/v1.0/AGENTS.md#nonexistent"],
        )
        assert [f["problem"] for f in found] == ["missing anchor"]

    def test_mapped_url_valid_anchor_passes(self, repo: Path) -> None:
        mod = _load_manifest()
        found = mod._check_links(
            repo,
            Path("docs/guia/README.md"),
            [f"{self.BASE}/blob/v1.0/AGENTS.md#agents"],
        )
        assert found == []

    def test_mapped_url_line_ref_is_not_an_anchor(self, repo: Path) -> None:
        mod = _load_manifest()
        found = mod._check_links(
            repo,
            Path("docs/guia/README.md"),
            [f"{self.BASE}/blob/v1.0/AGENTS.md#L10"],
        )
        assert found == []

    def test_backslash_escape_is_rejected(self, repo: Path) -> None:
        mod = _load_manifest()
        url = f"{self.BASE}/blob/v1.0/a%5C..%5C..%5Cx.md"
        assert mod._repo_url_path(url, self.SLUG, repo) is None

    def test_git_known_ref_wins_over_path_guess(self, repo: Path) -> None:
        mod = _load_manifest()
        init = subprocess.run(
            ["git", "-C", str(repo), "init", "-q"], capture_output=True, check=False
        )
        if init.returncode != 0:
            pytest.skip("git unavailable")
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "--allow-empty",
                "-qm",
                "init",
            ],
            check=True,
        )
        subprocess.run(["git", "-C", str(repo), "tag", "release/1.0"], check=True)
        # without the tag the longest existing path could win; with it the
        # real ref must decide the boundary.
        url = f"{self.BASE}/blob/release/1.0/AGENTS.md"
        assert mod._repo_url_path(url, self.SLUG, repo) == "AGENTS.md"
