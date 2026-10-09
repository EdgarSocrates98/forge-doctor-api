"""doc_catalogs.py — skills/agents catalog generation (Standard v1 Phase 6).

Scans the repo's real skill/agent definition dirs and emits
``docs/reference/skills.md`` and ``docs/reference/agents.md`` — name,
one-line summary (frontmatter ``description``/``summary`` or first
non-heading line), and path. Never invents entries; empty dirs produce an
honest "none" section.

stdlib-only::

    python doc_catalogs.py --repo . --out docs/reference
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

SKILL_DIRS = ("skills", ".claude/skills", ".devin/skills", ".agents/skills")
AGENT_DIRS = ("agents", ".claude/agents", ".devin/agents", ".agents/agents")
AGENT_SPEC_DIRS = ("agentic/agents",)  # AgentSpec/v1 TOML registries (the-forge)


def _summary(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    fm = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if fm:
        m = re.search(r"^(?:description|summary):\s*(.+)$", fm.group(1), re.MULTILINE)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("---"):
            return line[:160]
    return "—"


def _name(path: Path) -> str:
    if path.name in ("SKILL.md", "AGENT.md", "README.md"):
        return path.parent.name
    return path.stem


def scan(repo: Path, dirs: tuple[str, ...], nested_name: str | None) -> list[dict]:
    """Collect definitions. ``nested_name`` set = catalog ``<d>/<name>/FILE``;
    ``None`` = flat ``<d>/<name>.md``."""
    found: list[dict] = []
    for d in dirs:
        root = repo / d
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.md")):
            if nested_name is None:
                if p.name in ("README.md", "AGENT.md", "SKILL.md"):
                    continue  # handled by the nested scan / not a definition
                name = (
                    p.stem
                    if p.parent == root
                    else f"{p.parent.name}/{p.stem}"  # e.g. executors/sf-judge
                )
            elif p.name != nested_name:
                continue
            else:
                name = _name(p)
            found.append(
                {
                    "name": name if nested_name is None else _name(p),
                    "summary": _summary(p),
                    "path": p.relative_to(repo).as_posix(),
                }
            )
    # dedupe mirrors: same definition under agents/ and .agents/agents/ (the
    # latter often carries a forge prefix like ``sparkforge-azure-``) counts once
    seen: dict[str, dict] = {}
    for item in sorted(found, key=lambda x: len(x["name"])):  # shortest name wins
        key = re.sub(r"^(theforge|apiforge|platformforge|sparkforge-aws|sparkforge-azure|forge-doctor-(data|api))-",
                     "", item["name"])
        if not any(k == key or k.endswith("/" + key) or key.endswith("/" + k) for k in seen):
            seen[key] = item
    return sorted(seen.values(), key=lambda x: x["name"])


def scan_toml_specs(repo: Path, dirs: tuple[str, ...]) -> list[dict]:
    """AgentSpec/v1 registries — TOML files with ``id``/``authority``/
    ``summary`` fields (the-forge's eight specialists)."""
    import tomllib

    found: list[dict] = []
    for d in dirs:
        root = repo / d
        if not root.is_dir():
            continue
        for p in sorted(root.glob("*.toml")):
            try:
                spec = tomllib.loads(p.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError:
                continue
            name = spec.get("id") or spec.get("name") or p.stem
            auth = spec.get("authority", "")
            summary = (
                spec.get("summary") or spec.get("role")
                or spec.get("purpose") or spec.get("description") or "—"
            )
            summary = summary.strip().splitlines()[0][:160]
            if auth:
                summary = f"authority: {auth} — {summary}"
            found.append({"name": name, "summary": summary,
                          "path": p.relative_to(repo).as_posix()})
    return found


def emit(title: str, items: list[dict], note: str) -> str:
    out = [f"# {title}", "", note, ""]
    if not items:
        out.append("_None found in this repository — this is an honest empty catalog._")
        out.append("")
        return "\n".join(out)
    out += ["| name | summary | source |", "|---|---|---|"]
    for it in items:
        out.append(f"| `{it['name']}` | {it['summary']} | `{it['path']}` |")
    out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default="docs/reference")
    a = ap.parse_args()
    repo, out = Path(a.repo), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    skills = scan(repo, SKILL_DIRS, "SKILL.md")
    agents = scan(repo, AGENT_DIRS, "AGENT.md")
    # flat agents/<name>.md files are also agent definitions
    flat = scan(repo, AGENT_DIRS, None)
    names = {a["name"] for a in agents}
    agents += [a for a in flat if a["name"] not in names]
    names = {a["name"] for a in agents}
    agents += [a for a in scan_toml_specs(repo, AGENT_SPEC_DIRS) if a["name"] not in names]
    agents = sorted(agents, key=lambda x: x["name"])

    (out / "skills.md").write_text(
        emit("Skills catalog", skills, "Generated by `doc_catalogs.py` from the repo's skill dirs."), "utf-8")
    (out / "agents.md").write_text(
        emit("Agents catalog", agents, "Generated by `doc_catalogs.py` from the repo's agent dirs."), "utf-8")
    print(f"skills: {len(skills)}  agents: {len(agents)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
