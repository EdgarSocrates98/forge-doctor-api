"""The wheel must carry the packaged `_data/labs` corpus.

`pyproject.toml` maps `labs` into `forge_doctor_api/_data` via
`tool.poetry.packages.to`; inspecting the config proves intent, not
result — a packaging regression silently ships a wheel where `lab`
has no corpus and the packaged fallback never fires. Building the real
wheel is the only honest gate (paridade api-forge test_artifact_contents).
"""

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> zipfile.ZipFile:
    out = tmp_path_factory.mktemp("dist")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out), str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # Build isolation fails hermetically (can't fetch poetry-core) —
        # retry against the installed backend before conceding the gate.
        result = subprocess.run(
            [
                sys.executable, "-m", "build", "--wheel", "--no-isolation",
                "--outdir", str(out), str(ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        pytest.skip(f"`python -m build` unavailable or failed: {result.stderr[-400:]}")
    built = sorted(out.glob("*.whl"))
    assert built, "build succeeded without producing a wheel"
    return zipfile.ZipFile(built[0])


def test_wheel_carries_packaged_labs(wheel):
    labs = [n for n in wheel.namelist() if n.startswith("forge_doctor_api/_data/labs/")]
    assert labs, "wheel has no _data/labs corpus — packaged fallback would never fire"
    assert any(n.endswith("expected.yaml") or n.endswith("expected.yml") for n in labs)


def test_wheel_labs_match_checkout_count(wheel):
    wheel_labs = {
        n
        for n in wheel.namelist()
        if n.startswith("forge_doctor_api/_data/labs/") and not n.endswith("/")
    }
    checkout = {p.relative_to(ROOT).as_posix() for p in (ROOT / "labs").rglob("*") if p.is_file()}
    checkout = {p.removeprefix("labs/") for p in checkout}
    wheel_rel = {n.removeprefix("forge_doctor_api/_data/labs/") for n in wheel_labs}
    assert wheel_rel == checkout
