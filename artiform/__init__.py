"""ArtiForm: config-as-code for JFrog Artifactory."""

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path


def _read_version() -> str:
    # pyproject.toml is the single source of the version (bumped by tbump).
    # In a source checkout it sits next to this package and must win: an
    # editable install (developer venv, CI's pip install -e .) freezes the
    # dist-info version at install time, so after a bump the metadata would
    # lag behind pyproject.toml. An installed package has no pyproject.toml
    # next to it and reads its own metadata, like GitLabForm does.
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        with pyproject.open("rb") as fh:
            project = tomllib.load(fh)["project"]
        if project["name"] == "artiform":
            return project["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        pass
    try:
        return package_version("artiform")
    except PackageNotFoundError:
        return "unknown"


__version__ = _read_version()
