"""The HTTP layer against a real Artifactory OSS (vendor content types, auth,
error mapping), a dry run of the engine and the CLI, and how ArtiForm reports
the limits of OSS."""

import logging
import re

import pytest
import requests
import yaml

from artiform.cli import EXIT_OK, EXIT_PROCESSING_ERROR, main
from artiform.client import ArtifactoryClient
from artiform.exceptions import ApiError
from tests.acceptance.helpers import URL, changes, make_config, run


def test_version_is_parsed_from_vendor_content_type(client):
    # application/vnd.org.jfrog.artifactory.system.Version+json
    assert re.fullmatch(r"\d+\.\d+\.\d+", client.version())


def test_access_api_rejects_basic_auth():
    # The reason ArtiForm is token-only: /access answers 401 to basic auth
    # whatever the credentials.
    response = requests.get(f"{URL}/access/api/v1/projects", auth=("admin", "password"), timeout=30)

    assert response.status_code == 401
    assert "Unsupported authentication method Basic" in response.text


def test_invalid_token_is_an_api_error():
    with pytest.raises(ApiError) as exc:
        ArtifactoryClient(url=URL, token="not-a-token").version()

    assert exc.value.status_code == 401


def test_unknown_project_is_not_found(client, project_key):
    assert client.get_project(project_key) is None


def test_repositories_are_listed(client):
    repos = client.list_repositories()

    assert isinstance(repos, list)
    assert all("key" in repo for repo in repos)


def test_dry_run_plans_the_missing_project_without_creating_it(client, project_key):
    result = run(client, make_config(project_key, settings={"description": "acceptance"}), dry_run=True)

    assert not result.failed
    assert changes(result) == {("create", project_key)}
    assert client.get_project(project_key) is None


def test_cli_dry_run(tmp_path, project_key, caplog):
    # ARTIFACTORY_URL and ARTIFACTORY_TOKEN come from the environment.
    config = tmp_path / "artiform.yml"
    config.write_text(yaml.safe_dump({"config_version": 1, "projects": {project_key: {"display_name": "Acc"}}}))
    caplog.set_level(logging.INFO)

    assert main(["-c", str(config), "--dry-run"]) == EXIT_OK
    assert any(record.getMessage().startswith("Connected to Artifactory") for record in caplog.records)
    assert any(f"would create project/{project_key}" in record.getMessage() for record in caplog.records)


# -- limits of Artifactory OSS -------------------------------------------------


def test_pro_only_answer_is_not_mistaken_for_not_found(client):
    # The repository configuration API answers 400 on OSS, like it does for
    # an unknown key on licensed editions, but with a message; only the bare
    # "Bad Request" means not found.
    with pytest.raises(ApiError) as exc:
        client.get_repository("example-repo-local")

    assert exc.value.status_code == 400
    assert "Artifactory Pro" in str(exc.value)


def test_repositories_section_fails_cleanly(tmp_path, project_key, caplog):
    config = tmp_path / "artiform.yml"
    config.write_text(
        yaml.safe_dump(
            {
                "config_version": 1,
                "projects": {
                    project_key: {
                        "repositories": {f"{project_key}-generic-local": {"type": "local", "package_type": "generic"}}
                    }
                },
            }
        )
    )
    caplog.set_level(logging.INFO)

    assert main(["-c", str(config), "--dry-run"]) == EXIT_PROCESSING_ERROR
    assert any("Artifactory Pro" in record.getMessage() for record in caplog.records)
