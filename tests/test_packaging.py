"""Packaging checks: `rf --version` and the data files a wheel install needs."""
import contextlib
import io
import re
from pathlib import Path

from rejected_futures.cli import main

ROOT = Path(__file__).resolve().parent.parent


def declared_version():
    """The version declared in pyproject.toml."""
    text = (ROOT / "pyproject.toml").read_text()
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10 has no tomllib
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        assert m, "no version in pyproject.toml"
        return m.group(1)
    return tomllib.loads(text)["project"]["version"]


def test_version_flag_prints_declared_version():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            code = main(["--version"])
        except SystemExit as e:
            code = e.code
    assert code == 0
    assert out.getvalue().strip() == f"rf {declared_version()}"


def test_wheel_data_files_are_importable():
    from importlib.resources import files

    root = files("rejected_futures")
    model = (root / "model.json").read_text()
    assert model.strip(), "model.json is empty"
    command = (root / "commands" / "rf-mine.md").read_text()
    assert command.strip(), "commands/rf-mine.md is empty"
