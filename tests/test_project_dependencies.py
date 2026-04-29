from pathlib import Path
import tomllib


def test_runtime_dependencies_do_not_include_playwright() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    dependencies = pyproject["project"]["dependencies"]

    assert not any(dependency.startswith("playwright") for dependency in dependencies)


def test_console_script_is_sca_only() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]

    assert scripts == {"sca": "switchgpt.cli:main"}
