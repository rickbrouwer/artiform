import logging
import tomllib
from pathlib import Path

import pytest

import artiform
from artiform import __version__
from artiform.cli import EXIT_INPUT_ERROR, main

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def test_version_comes_from_pyproject():
    # pyproject.toml is the single source of truth (bumped by tbump); the
    # package must report exactly that, also when run from source.
    assert __version__ == _pyproject_version()


def test_source_checkout_wins_over_stale_installed_metadata(monkeypatch):
    # An editable install keeps the dist-info version from install time, so
    # right after a tbump bump the metadata lags behind pyproject.toml.
    monkeypatch.setattr(artiform, "package_version", lambda name: "0.0.0-stale")

    assert artiform._read_version() == _pyproject_version()


def test_tbump_current_version_matches_pyproject():
    with (ROOT / "tbump.toml").open("rb") as fh:
        assert tomllib.load(fh)["version"]["current"] == __version__


def test_run_starts_with_version_line(tmp_path, caplog):
    caplog.set_level(logging.INFO)

    rc = main(["-c", str(tmp_path / "missing.yml")])

    assert rc == EXIT_INPUT_ERROR
    assert caplog.records[0].getMessage() == f"ArtiForm version: {__version__}"


def test_version_flag_matches_package_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"artiform {__version__}"
