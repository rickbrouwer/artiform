import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from artiform.exceptions import ApiError, NotFoundError

logger = logging.getLogger("artiform")

# POST is deliberately excluded: creates are not guaranteed idempotent.
RETRIED_METHODS = frozenset({"GET", "PUT", "DELETE"})
RETRIED_STATUSES = (429, 500, 502, 503, 504)


class ArtifactoryClient:
    """Thin typed wrapper around the Artifactory and Access REST APIs.

    The base URL is the platform root (https://host), with the Artifactory
    API under /artifactory and the Access API under /access.
    """

    def __init__(
        self,
        url: str,
        token: str,
        verify_ssl: bool = True,
        timeout: int = 30,
    ):
        self.base_url = url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        # Bearer tokens (reference or identity) work on both /artifactory
        # and /access; basic auth is rejected on /access by many instances.
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.session.verify = verify_ssl
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=RETRIED_STATUSES,
            allowed_methods=RETRIED_METHODS,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    # -- low level -----------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        json_body: Any = None,
        params: dict | None = None,
    ) -> Any:
        url = self.base_url + path
        logger.debug("%s %s", method, url)
        try:
            response = self.session.request(method, url, json=json_body, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            # Wrap transport errors so per-entity error handling catches them
            # and the run can continue with the remaining work.
            raise ApiError(0, f"{method} {path}: {exc}") from exc
        if response.status_code == 404:
            raise NotFoundError(f"{method} {path}: 404 {response.text[:300]}")
        if not response.ok:
            raise ApiError(
                response.status_code,
                f"{method} {path}: {response.status_code} {response.text[:500]}",
            )
        # Artifactory often uses vendor types like
        # application/vnd.org.jfrog.artifactory.system.Version+json
        content_type = response.headers.get("Content-Type", "")
        if "json" in content_type.lower() and response.content:
            try:
                return response.json()
            except ValueError as exc:
                # Covers requests' JSONDecodeError, which is also a
                # RequestException; left unwrapped it would bypass the
                # per-entity error isolation and abort the whole run
                # without naming the endpoint.
                if method == "GET":
                    raise ApiError(
                        response.status_code,
                        f"{method} {path}: response claims {content_type} but "
                        f"the body is not valid JSON: {response.text[:300]!r}",
                    ) from exc
                # Some write endpoints answer 200 with a JSON content type
                # but a plain-text body (e.g. DELETE cleanup policy returns
                # "... was deleted successfully."). The status code already
                # confirmed success, so the body is informational only.
                logger.debug(
                    "%s %s: ignoring non-JSON body with %s content type: %r",
                    method,
                    path,
                    content_type,
                    response.text[:300],
                )
                return response.text
        return response.text

    def _get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _get_or_none(self, path: str) -> Any | None:
        try:
            return self._get(path)
        except NotFoundError:
            return None

    # -- system --------------------------------------------------------------

    def version(self) -> str:
        return self._get("/artifactory/api/system/version")["version"]

    # -- projects (Access API) -----------------------------------------------

    def list_projects(self) -> list[dict]:
        return self._get("/access/api/v1/projects")

    def get_project(self, project_key: str) -> dict | None:
        return self._get_or_none(f"/access/api/v1/projects/{project_key}")

    def create_project(self, payload: dict) -> None:
        self._request("POST", "/access/api/v1/projects", json_body=payload)

    def update_project(self, project_key: str, payload: dict) -> None:
        self._request("PUT", f"/access/api/v1/projects/{project_key}", json_body=payload)

    def delete_project(self, project_key: str) -> None:
        self._request("DELETE", f"/access/api/v1/projects/{project_key}")

    # -- repositories (Artifactory API) ----------------------------------------

    def list_repositories(self, project_key: str | None = None) -> list[dict]:
        params = {"project": project_key} if project_key else None
        return self._get("/artifactory/api/repositories", params=params)

    def get_repository(self, repo_key: str) -> dict | None:
        try:
            return self._get(f"/artifactory/api/repositories/{repo_key}")
        except NotFoundError:
            return None
        except ApiError as exc:
            # This endpoint answers a bare 400 "Bad Request" for unknown repo
            # keys; 400s with a specific message are real errors.
            if exc.status_code == 400 and "Bad Request" in str(exc):
                return None
            raise

    def create_repository(self, repo_key: str, payload: dict) -> None:
        self._request("PUT", f"/artifactory/api/repositories/{repo_key}", json_body=payload)

    def update_repository(self, repo_key: str, payload: dict) -> None:
        # POST is a partial merge: only the provided fields change.
        self._request("POST", f"/artifactory/api/repositories/{repo_key}", json_body=payload)

    def delete_repository(self, repo_key: str) -> None:
        self._request("DELETE", f"/artifactory/api/repositories/{repo_key}")

    def attach_repository(self, repo_key: str, project_key: str, force: bool = True) -> None:
        self._request(
            "PUT",
            f"/access/api/v1/projects/_/attach/repositories/{repo_key}/{project_key}",
            params={"force": str(force).lower()},
        )

    # -- project sharing of repositories (Access API) ---------------------------

    def get_repository_project_status(self, repo_key: str) -> dict | None:
        """Assignment and sharing state of a repo; None if the repo is unknown."""
        return self._get_or_none(f"/access/api/v1/projects/_/repositories/{repo_key}")

    def share_repository(self, repo_key: str, target_project_key: str, read_only: bool) -> None:
        self._request(
            "PUT",
            f"/access/api/v1/projects/_/share/repositories/{repo_key}/{target_project_key}",
            params={"readOnly": str(read_only).lower()},
        )

    def unshare_repository(self, repo_key: str, target_project_key: str) -> None:
        self._request(
            "DELETE",
            f"/access/api/v1/projects/_/share/repositories/{repo_key}/{target_project_key}",
        )

    def share_repository_with_all(self, repo_key: str, read_only: bool) -> None:
        self._request(
            "PUT",
            f"/access/api/v1/projects/_/share/repositories/{repo_key}",
            params={"readOnly": str(read_only).lower()},
        )

    def unshare_repository_with_all(self, repo_key: str) -> None:
        self._request("DELETE", f"/access/api/v1/projects/_/share/repositories/{repo_key}")

    # -- groups (Access API v2) ------------------------------------------------

    def get_group(self, name: str) -> dict | None:
        return self._get_or_none(f"/access/api/v2/groups/{name}")

    def import_ldap_group(self, name: str, ldap_group_setting: str) -> None:
        self._request(
            "POST",
            "/access/api/v2/groups",
            json_body={"name": name, "import_from_ldap_group_setting": ldap_group_setting},
        )

    # -- project membership (Access API) ---------------------------------------

    def list_project_members(self, project_key: str, kind: str) -> list[dict]:
        """kind is 'users' or 'groups'; returns a list of {name, roles} dicts."""
        data = self._get(f"/access/api/v1/projects/{project_key}/{kind}")
        if isinstance(data, dict):
            return data.get("members", [])
        return data

    def set_project_member(self, project_key: str, kind: str, name: str, roles: list[str]) -> None:
        self._request(
            "PUT",
            f"/access/api/v1/projects/{project_key}/{kind}/{name}",
            json_body={"roles": roles},
        )

    def remove_project_member(self, project_key: str, kind: str, name: str) -> None:
        self._request("DELETE", f"/access/api/v1/projects/{project_key}/{kind}/{name}")

    # -- package cleanup policies ----------------------------------------------

    def list_cleanup_policies(self, project_key: str) -> list[dict]:
        data = self._get(
            "/artifactory/api/cleanup/packages/policies",
            params={"projectKey": project_key},
        )
        if isinstance(data, dict):
            return data.get("policies", [])
        return data

    def get_cleanup_policy(self, policy_key: str) -> dict | None:
        return self._get_or_none(f"/artifactory/api/cleanup/packages/policies/{policy_key}")

    def create_cleanup_policy(self, policy_key: str, payload: dict) -> None:
        self._request(
            "POST",
            f"/artifactory/api/cleanup/packages/policies/{policy_key}",
            json_body=payload,
        )

    def update_cleanup_policy(self, policy_key: str, payload: dict) -> None:
        self._request(
            "PUT",
            f"/artifactory/api/cleanup/packages/policies/{policy_key}",
            json_body=payload,
        )

    def set_cleanup_policy_enabled(self, policy_key: str, enabled: bool) -> None:
        self._request(
            "POST",
            f"/artifactory/api/cleanup/packages/policies/{policy_key}/enablement",
            json_body={"enabled": enabled},
        )

    def delete_cleanup_policy(self, policy_key: str) -> None:
        self._request("DELETE", f"/artifactory/api/cleanup/packages/policies/{policy_key}")
