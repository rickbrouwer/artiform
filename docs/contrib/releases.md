# Releases

## Versioning

ArtiForm follows [PEP 440](https://peps.python.org/pep-0440/), which for
this project means [semantic versioning](https://semver.org/): a new major
version signals a breaking change to the config format or to a safety
guarantee, a minor version adds behavior, a patch version fixes bugs.
Before 1.0.0 minor versions may also contain breaking changes; the
[changelog](../changelog.md) lists them under `Breaking Changes`.

The version lives in `pyproject.toml`. `artiform --version` and the
`ArtiForm version:` line at the start of every run read it from there in a
source checkout, and from the installed package metadata otherwise.

## Container image

Every release publishes a container image to GitHub Container Registry:

| Tag | Example | Meaning |
|---|---|---|
| `<major>.<minor>.<patch>` | `ghcr.io/rickbrouwer/artiform:0.1.0` | Exactly this release. Pin this in a pipeline that applies changes |
| `<major>.<minor>` | `ghcr.io/rickbrouwer/artiform:0.1` | Latest patch release of this minor version |
| `<major>` | `ghcr.io/rickbrouwer/artiform:1` | Latest release of this major version; not published for 0.x |
| `latest` | `ghcr.io/rickbrouwer/artiform:latest` | Most recent release |

The image is built for `linux/amd64` and `linux/arm64` from the `Dockerfile`
in this repository and contains ArtiForm and its dependencies, nothing else.
Environments that cannot pull from `ghcr.io`, or that need a CA bundle or a
mirrored base image, build it from the tagged source with the same
`Dockerfile`; see [Running](../running.md#gitlab-ci).

## Release procedure (maintainers)

1. On an up-to-date `main`, add a `## <version>` entry to
   [changelog.md](../changelog.md) and commit it.
2. Run `pipx run tbump <version>` ([tbump](https://github.com/your-tools/tbump);
   install [pipx](https://pypa.github.io/pipx/installation/) first if
   needed). tbump checks that the changelog entry exists, writes the new
   version to `pyproject.toml` and `tbump.toml`, commits, tags the commit
   `v<version>` and pushes commit and tag.
3. The tag triggers the `Release` workflow (`.github/workflows/release.yml`):
   it verifies that the tag matches the version in `pyproject.toml`, runs
   the test suite, and builds and pushes the image with the tags listed
   above. The workflow authenticates with the run's own `GITHUB_TOKEN`; the
   repository holds no registry credentials.
