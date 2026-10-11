"""requirements.txt (Streamlit Cloud) must pin exactly what constraints.txt (CI) pins."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pins(name: str) -> list[str]:
    lines = (ROOT / name).read_text().splitlines()
    return [ln.split(" #")[0].strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def _name(req: str) -> str:
    return re.split(r"[<>=!~;\[ ]", req, maxsplit=1)[0].lower().replace("_", "-")


def test_requirements_match_constraints():
    assert _pins("requirements.txt") == _pins("constraints.txt")


def test_every_dependency_is_pinned():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    pinned = {_name(p) for p in _pins("requirements.txt")}
    assert all("==" in p for p in _pins("requirements.txt"))
    assert {_name(d) for d in deps} <= pinned
