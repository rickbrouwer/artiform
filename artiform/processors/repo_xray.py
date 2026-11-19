"""Xray indexing configuration of a repository (the reserved 'xray' key).

Mirrors the Xray repos_config API: settings of the repository as a whole
(retention_in_days, vuln_contextual_analysis, exposures, ...) live in
repo_config, path patterns with their own retention in repo_paths_config.
The config flattens both into one mapping; this module parses it, builds
the API payload and normalizes the GET response to the same shape so the
generic asymmetric diff applies.
"""

from artiform.exceptions import ApiError, ConfigError

PATTERN_KEYS = ("include", "exclude", "index_new_artifacts", "retention_in_days")
OTHER_ARTIFACTS_KEYS = ("index_new_artifacts", "retention_in_days")
# Keys of the flat config that belong to repo_paths_config; the rest is
# repo_config and passed through.
PATHS_KEYS = ("patterns", "all_other_artifacts")
# Only repositories Xray can index; virtuals hold no artifacts of their own.
INDEXABLE_RCLASSES = ("local", "remote", "federated")


def parse_xray_config(project_key: str, repo_key: str, rclass: str, xray_cfg) -> dict:
    where = f"{project_key}.repositories.{repo_key}.xray"
    if not isinstance(xray_cfg, dict) or not xray_cfg:
        raise ConfigError(f"{where} must be a non-empty mapping")
    if rclass not in INDEXABLE_RCLASSES:
        raise ConfigError(f"{where}: only local, remote and federated repositories can be indexed by Xray")
    state = {k: v for k, v in xray_cfg.items() if k not in PATHS_KEYS}
    if "retention_in_days" in state:
        _require_days(state["retention_in_days"], f"{where}.retention_in_days")
    patterns = xray_cfg.get("patterns")
    other = xray_cfg.get("all_other_artifacts")
    if patterns is not None:
        if "retention_in_days" in state:
            # The API ignores the repo-level value as soon as patterns are
            # sent; rejecting the combination keeps the config honest.
            raise ConfigError(f"{where}: 'retention_in_days' and 'patterns' are mutually exclusive")
        if not isinstance(patterns, list) or not patterns:
            raise ConfigError(f"{where}.patterns must be a non-empty list of pattern mappings")
        if other is None:
            raise ConfigError(f"{where}.all_other_artifacts is required with 'patterns' (artifacts matching none)")
        state["patterns"] = [_parse_pattern(p, f"{where}.patterns[{i}]") for i, p in enumerate(patterns)]
        state["all_other_artifacts"] = _parse_other_artifacts(other, f"{where}.all_other_artifacts")
    elif other is not None:
        raise ConfigError(f"{where}.all_other_artifacts only applies together with 'patterns'")
    else:
        # Authoritative: patterns left on the server are drift, or Xray would
        # keep ignoring the repo-wide retention while reporting "up to date".
        state["patterns"] = []
    return state


def _parse_pattern(pattern, where: str) -> dict:
    if not isinstance(pattern, dict):
        raise ConfigError(f"{where} must be a mapping")
    unknown = set(pattern) - set(PATTERN_KEYS)
    if unknown:
        raise ConfigError(
            f"Unknown keys in {where}: {', '.join(sorted(unknown))} (expected one of: {', '.join(PATTERN_KEYS)})"
        )
    include = pattern.get("include")
    if not isinstance(include, str) or not include:
        raise ConfigError(f"{where}.include must be a non-empty path pattern")
    exclude = pattern.get("exclude", "")
    if not isinstance(exclude, str):
        raise ConfigError(f"{where}.exclude must be a string")
    if "retention_in_days" not in pattern:
        raise ConfigError(f"{where}.retention_in_days is required")
    _require_days(pattern["retention_in_days"], f"{where}.retention_in_days")
    return {
        "include": include,
        "exclude": exclude,
        "index_new_artifacts": _require_bool(pattern.get("index_new_artifacts", True), f"{where}.index_new_artifacts"),
        "retention_in_days": pattern["retention_in_days"],
    }


def _parse_other_artifacts(other, where: str) -> dict:
    if not isinstance(other, dict):
        raise ConfigError(f"{where} must be a mapping")
    unknown = set(other) - set(OTHER_ARTIFACTS_KEYS)
    if unknown:
        raise ConfigError(
            f"Unknown keys in {where}: {', '.join(sorted(unknown))} "
            f"(expected one of: {', '.join(OTHER_ARTIFACTS_KEYS)})"
        )
    if "retention_in_days" not in other:
        raise ConfigError(f"{where}.retention_in_days is required")
    _require_days(other["retention_in_days"], f"{where}.retention_in_days")
    return {
        "index_new_artifacts": _require_bool(other.get("index_new_artifacts", True), f"{where}.index_new_artifacts"),
        "retention_in_days": other["retention_in_days"],
    }


def _require_days(value, where: str) -> None:
    # bool is an int subclass; 'true' must not pass as 1 day.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{where} must be a positive number of days, got {value!r}")


def _require_bool(value, where: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{where} must be a boolean (true/false), got {value!r}")
    return value


def xray_payload(desired: dict, current: dict | None = None) -> dict:
    """Body for PUT repos_config (without repo_name). The PUT replaces the
    configuration, so repo_config settings the config does not manage
    (e.g. exposures set in the UI) are carried over from the current state."""
    payload: dict = {}
    repo_config = {k: v for k, v in (current or {}).items() if k not in PATHS_KEYS}
    repo_config.update({k: v for k, v in desired.items() if k not in PATHS_KEYS})
    if repo_config:
        payload["repo_config"] = repo_config
    if desired.get("patterns"):
        payload["repo_paths_config"] = {
            "patterns": desired["patterns"],
            "all_other_artifacts": desired["all_other_artifacts"],
        }
    return payload


def current_xray_state(repo_key: str, response) -> dict:
    """Flatten a GET repos_config response like the config. Pattern objects
    keep only the known keys so a server-added field never flags drift
    (lists are compared whole); an omitted boolean reads as false, like a
    JSON encoder that drops empty values would have written it."""
    if response is None:
        return {"patterns": []}
    if not isinstance(response, dict):
        raise ApiError(0, f"GET /xray/api/v1/repos_config/{repo_key}: expected JSON, got {str(response)[:300]!r}")
    state = dict(response.get("repo_config") or {})
    paths = response.get("repo_paths_config") or {}
    state["patterns"] = [
        {
            "include": p.get("include"),
            "exclude": p.get("exclude") or "",
            "index_new_artifacts": bool(p.get("index_new_artifacts")),
            "retention_in_days": p.get("retention_in_days"),
        }
        for p in paths.get("patterns") or []
    ]
    if paths.get("all_other_artifacts") is not None:
        other = paths["all_other_artifacts"]
        state["all_other_artifacts"] = {
            "index_new_artifacts": bool(other.get("index_new_artifacts")),
            "retention_in_days": other.get("retention_in_days"),
        }
    return state
