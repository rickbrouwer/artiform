"""Fixtures for the acceptance tests, which run against a real Artifactory OSS.

The tests need ARTIFACTORY_URL and ARTIFACTORY_TOKEN (an admin token); the
tests/acceptance/artifactory.sh script starts a disposable instance and
prints both. Without them every test here is skipped with a reason. A plain
`pytest` runs the unit tests only (testpaths in pyproject.toml); this
directory is run explicitly with `pytest tests/acceptance`.

The tests create nothing on the server: Artifactory OSS supports none of the
project management (see docs/contrib/development.md), so they cover the HTTP
layer and the dry-run path. Every test still gets its own random project key
so a run never collides with anything that exists on the instance.
"""

from __future__ import annotations

import uuid

import pytest

from artiform.client import ArtifactoryClient
from tests.acceptance.helpers import TOKEN, URL


def pytest_collection_modifyitems(config, items):
    if URL and TOKEN:
        return
    skip = pytest.mark.skip(reason="acceptance tests need ARTIFACTORY_URL and ARTIFACTORY_TOKEN")
    for item in items:
        item.add_marker(skip)


@pytest.fixture(scope="session")
def client() -> ArtifactoryClient:
    return ArtifactoryClient(url=URL, token=TOKEN)


@pytest.fixture
def project_key() -> str:
    # Project keys: lowercase alphanumerics, starting with a letter.
    return "acc" + uuid.uuid4().hex[:8]
