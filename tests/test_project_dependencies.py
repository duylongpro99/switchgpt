from pathlib import Path
import tomllib


def test_runtime_dependencies_do_not_include_playwright() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    dependencies = pyproject["project"]["dependencies"]

    assert not any(dependency.startswith("playwright") for dependency in dependencies)
