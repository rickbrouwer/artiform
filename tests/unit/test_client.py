import pytest
import requests

from artiform.client import ArtifactoryClient
from artiform.exceptions import ApiError, NotFoundError


@pytest.fixture
def client():
    return ArtifactoryClient("https://fake.example.com/", token="my-token")


class FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None, content_type=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data
        self.ok = status_code < 400
        if content_type is None and json_data is not None:
            content_type = "application/json"
        self.headers = {"Content-Type": content_type} if content_type else {}
        self.content = b"x" if json_data is not None else b""

    def json(self):
        if self._json is None:
            raise requests.exceptions.JSONDecodeError("Expecting value", self.text, 0)
        return self._json


def test_transport_errors_are_wrapped_in_api_error(client, monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(client.session, "request", boom)
    with pytest.raises(ApiError) as excinfo:
        client.get_project("team-x")
    assert not isinstance(excinfo.value, NotFoundError)
    assert "connection refused" in str(excinfo.value)


def test_404_raises_not_found(client, monkeypatch):
    monkeypatch.setattr(client.session, "request", lambda *a, **kw: FakeResponse(404, "nope"))
    assert client.get_project("team-x") is None
    with pytest.raises(NotFoundError):
        client.create_project({"project_key": "x"})


def test_get_repository_treats_400_as_not_found(client, monkeypatch):
    # The repositories endpoint answers 400 Bad Request for unknown keys.
    monkeypatch.setattr(client.session, "request", lambda *a, **kw: FakeResponse(400, "Bad Request"))
    assert client.get_repository("nope-local") is None


def test_create_repository_400_still_raises(client, monkeypatch):
    monkeypatch.setattr(client.session, "request", lambda *a, **kw: FakeResponse(400, "Bad Request"))
    with pytest.raises(ApiError):
        client.create_repository("key", {})


def test_http_error_raises_api_error_with_context(client, monkeypatch):
    monkeypatch.setattr(client.session, "request", lambda *a, **kw: FakeResponse(409, "conflict"))
    with pytest.raises(ApiError) as excinfo:
        client.create_project({"project_key": "x"})
    assert excinfo.value.status_code == 409
    assert "conflict" in str(excinfo.value)


def test_json_response_is_parsed(client, monkeypatch):
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **kw: FakeResponse(200, json_data={"version": "7.150.0"}),
    )
    assert client.version() == "7.150.0"


def test_vendor_json_content_type_is_parsed(client, monkeypatch):
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *a, **kw: FakeResponse(
            200,
            json_data={"version": "7.150.0"},
            content_type="application/vnd.org.jfrog.artifactory.system.Version+json",
        ),
    )
    assert client.version() == "7.150.0"


def test_invalid_json_body_raises_api_error_naming_the_endpoint(client, monkeypatch):
    # A 2xx response with a JSON Content-Type but a non-JSON body must become
    # an ApiError that names the endpoint. requests' own JSONDecodeError is a
    # RequestException, which would skip the per-entity error isolation and
    # kill the whole run with only "Expecting value: line 1 column 1".
    response = FakeResponse(200, text="OK", content_type="application/json")
    response.content = b"OK"
    monkeypatch.setattr(client.session, "request", lambda *a, **kw: response)
    with pytest.raises(ApiError) as excinfo:
        client.list_projects()
    assert "/access/api/v1/projects" in str(excinfo.value)
    assert "'OK'" in str(excinfo.value)


def test_write_with_non_json_body_and_json_content_type_succeeds(client, monkeypatch):
    # DELETE /cleanup/packages/policies/{key} answers 200 with Content-Type
    # application/json but a plain-text body ("... was deleted successfully.").
    # For writes the status code is the result, so this must not raise.
    response = FakeResponse(
        200,
        text="Package Cleanup Policy x was deleted successfully.",
        content_type="application/json",
    )
    response.content = response.text.encode()
    monkeypatch.setattr(client.session, "request", lambda *a, **kw: response)
    client.delete_cleanup_policy("x")  # must not raise


def test_base_url_trailing_slash_is_stripped(client):
    assert client.base_url == "https://fake.example.com"


def test_token_is_sent_as_bearer_header(client):
    assert client.session.headers["Authorization"] == "Bearer my-token"
    assert client.session.auth is None
