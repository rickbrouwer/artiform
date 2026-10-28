# Releases

## Versioning

We try to follow the [PEP 440](https://peps.python.org/pep-0440/) versioning scheme, which is mostly based on [semantic versioning](https://semver.org/).

The version lives in `pyproject.toml` (tbump mirrors it into `tbump.toml`). `artiform --version` and the `ArtiForm version:` line at the start of every run read it from there in a source checkout, and from the installed package metadata otherwise.

## Procedure

1. Make sure you're on `main` branch and it is up-to-date.
2. Add an entry in [changelog.md](../changelog.md). Commit this change.
3. Update version using [`tbump`](https://github.com/your-tools/tbump). Run `pipx run tbump <new-semantic-version-number>`.

    **Note**: You may need to install `pipx` first if it's not already installed. Follow the instructions at [`pipx` documentation](https://pypa.github.io/pipx/installation/).

    Executing `tbump` will check that the changelog has a `## <new-version>` heading, create a commit containing version updates to necessary files (i.e. `tbump.toml`, `pyproject.toml`), create a new tag for the new version from the current `ref` in `main` branch, and finally push the commit and tag to remote.

4. Build and publish the container image from the new tag with your own pipeline; this repository ships only the `Dockerfile`.
