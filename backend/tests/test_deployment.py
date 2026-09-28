import tomllib
from pathlib import Path


def _requirements(path: Path) -> list[str]:
    return [
        line
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    ]


def test_vercel_requirements_match_backend_runtime_requirements():
    repository_root = Path(__file__).resolve().parents[2]
    backend_requirements = _requirements(repository_root / "backend" / "requirements.txt")
    backend_project = tomllib.loads(
        (repository_root / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert _requirements(repository_root / "requirements.txt") == backend_requirements
    assert backend_project["dependencies"] == backend_requirements
    assert backend_project["requires-python"] == ">=3.11"
