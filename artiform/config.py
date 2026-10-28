import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from artiform.exceptions import ConfigError
from artiform.util import deep_merge

SUPPORTED_CONFIG_VERSION = 1

KNOWN_TOP_LEVEL_KEYS = {
    "config_version",
    "artifactory",
    "defaults",
    "enforce_projects",
    "include_projects",
    "projects",
}
KNOWN_ARTIFACTORY_KEYS = {"url", "token", "verify_ssl", "timeout"}
KNOWN_DEFAULTS_KEYS = {"project", "repository", "cleanup_policy"}
PROJECT_SETTINGS_KEYS = {
    "display_name",
    "description",
    "admin_privileges",
    "storage_quota_bytes",
}
PROJECT_SECTION_KEYS = {"repositories", "members", "cleanup_policies"}

# 2-32 chars, lowercase alphanumeric plus hyphens, starting with a letter.
PROJECT_KEY_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")

# $VAR or ${VAR} (POSIX-style names); $$ is a literal dollar sign. The final
# bare '${' alternative catches malformed references (missing closing brace,
# invalid name) so they error instead of passing through as literal text.
ENV_VAR_RE = re.compile(r"\$\$|\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)|\$\{")


@dataclass
class ArtifactorySettings:
    url: str
    token: str
    verify_ssl: bool = True
    timeout: int = 30


@dataclass
class ProjectConfig:
    key: str
    settings: dict
    sections: dict


@dataclass
class Config:
    artifactory: ArtifactorySettings
    projects: dict[str, ProjectConfig]
    enforce_projects: bool = False


def load_config(path: str | Path) -> Config:
    path = Path(path)
    raw = _load_yaml_mapping(path)
    # Substituted separately because it is consumed here, before the
    # substitution pass over the merged config.
    include = _substitute_env(raw.pop("include_projects", None))
    if include is not None:
        _merge_included_projects(raw, include, path)
    return parse_config(_substitute_env(raw))


def _substitute_env(value):
    """Replace $VAR / ${VAR} references in string values with the value of
    that environment variable (typically a CI variable holding a secret,
    such as a remote repository password). Strict by design: an unset
    variable aborts the run, because an empty credential applied to
    Artifactory would be hard to notice. $$ escapes a literal dollar."""
    if isinstance(value, str):

        def replace(match: re.Match) -> str:
            if match.group(0) == "$$":
                return "$"
            name = match.group(1) or match.group(2)
            if name is None:
                raise ConfigError(
                    f"Malformed environment variable reference in {value!r}: "
                    "expected ${NAME} with a valid name and closing brace "
                    "($$ for a literal dollar)"
                )
            # An empty value is as dangerous as an unset one: it would apply
            # an empty credential.
            if not os.environ.get(name):
                raise ConfigError(
                    f"Environment variable {name!r} referenced in the config "
                    f"(as {match.group(0)!r}) is not set or empty"
                )
            return os.environ[name]

        return ENV_VAR_RE.sub(replace, value)
    if isinstance(value, dict):
        return {key: _substitute_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute_env(item) for item in value]
    return value


def _load_yaml_mapping(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {path} must contain a YAML mapping")
    return raw


def _merge_included_projects(raw: dict, include, config_path: Path) -> None:
    """Load per-team project files (globs relative to the main config file)
    into raw['projects']. Strict by design: a broken or empty team file, a
    pattern matching nothing, or a duplicate project key aborts the whole
    run, because a silently missing project combined with enforce_projects
    would delete it."""
    patterns = [include] if isinstance(include, str) else include
    if not isinstance(patterns, list) or not patterns or not all(isinstance(p, str) for p in patterns):
        raise ConfigError("include_projects must be a glob pattern or a list of glob patterns")
    base = config_path.parent
    files: dict[Path, None] = {}
    for pattern in patterns:
        matches = [match for match in sorted(base.glob(pattern)) if match.resolve() != config_path.resolve()]
        if not matches:
            raise ConfigError(f"include_projects pattern {pattern!r} matched no files (relative to {base})")
        files.update(dict.fromkeys(matches))

    main_projects = dict(raw.get("projects") or {})
    sources = {key: str(config_path) for key in main_projects}
    included: dict = {}
    for file in files:
        data = _load_yaml_mapping(file)
        if set(data) != {"projects"} or not isinstance(data["projects"], dict) or not data["projects"]:
            raise ConfigError(
                f"Included file {file} must contain exactly one non-empty "
                "'projects' mapping (other top-level settings belong in the "
                "main config file)"
            )
        for key, cfg in data["projects"].items():
            if key in sources:
                raise ConfigError(f"Project {key!r} is defined in both {sources[key]} and {file}")
            sources[key] = str(file)
            included[key] = cfg
    # Included (team) projects come before the main file's own (platform)
    # projects. The engine creates all projects before any section and
    # reorders projects by their virtual repositories' dependencies, so this
    # only decides the order among independent projects.
    raw["projects"] = {**included, **main_projects}


def parse_config(raw: dict) -> Config:
    _require_known_keys(raw, KNOWN_TOP_LEVEL_KEYS, "top level")
    if "include_projects" in raw:
        raise ConfigError("include_projects is only supported when loading from a config file")

    version = raw.get("config_version")
    if version != SUPPORTED_CONFIG_VERSION:
        raise ConfigError(f"config_version must be {SUPPORTED_CONFIG_VERSION}, got {version!r}")

    artifactory = _parse_artifactory(raw.get("artifactory") or {})
    defaults = _parse_defaults(raw.get("defaults") or {})
    enforce_projects = raw.get("enforce_projects", False)
    # Strict on purpose: env var substitution always produces strings, and
    # bool("false") is True, which would silently enable mass deletion.
    if not isinstance(enforce_projects, bool):
        raise ConfigError(
            f"enforce_projects must be true or false, got {enforce_projects!r} "
            "(environment variable substitution produces strings, which are "
            "not accepted here)"
        )

    projects_raw = raw.get("projects") or {}
    if not isinstance(projects_raw, dict):
        raise ConfigError("'projects' must be a mapping of project key to settings")
    if enforce_projects and not projects_raw:
        raise ConfigError(
            "enforce_projects is true but no projects are defined; this would delete every project on the instance"
        )

    projects = {key: _parse_project(key, cfg or {}, defaults) for key, cfg in projects_raw.items()}
    return Config(
        artifactory=artifactory,
        projects=projects,
        enforce_projects=enforce_projects,
    )


def _parse_artifactory(section: dict) -> ArtifactorySettings:
    if not isinstance(section, dict):
        raise ConfigError("'artifactory' must be a mapping")
    _require_known_keys(section, KNOWN_ARTIFACTORY_KEYS, "artifactory")
    url = os.environ.get("ARTIFACTORY_URL") or section.get("url")
    token = os.environ.get("ARTIFACTORY_TOKEN") or section.get("token")
    if not url:
        raise ConfigError("Artifactory URL missing: set artifactory.url or ARTIFACTORY_URL")
    if not token:
        raise ConfigError(
            "Token missing: set an access token (reference or identity) via artifactory.token or ARTIFACTORY_TOKEN"
        )
    return ArtifactorySettings(
        url=url,
        token=token,
        verify_ssl=bool(section.get("verify_ssl", True)),
        timeout=int(section.get("timeout", 30)),
    )


def _parse_defaults(section: dict) -> dict:
    if not isinstance(section, dict):
        raise ConfigError("'defaults' must be a mapping")
    _require_known_keys(section, KNOWN_DEFAULTS_KEYS, "defaults")
    for key, value in section.items():
        if not isinstance(value, dict):
            raise ConfigError(f"defaults.{key} must be a mapping")
    return section


def _parse_project(key: str, cfg: dict, defaults: dict) -> ProjectConfig:
    if not PROJECT_KEY_RE.match(key):
        raise ConfigError(
            f"Invalid project key {key!r}: must be 2-32 chars, lowercase "
            "alphanumeric or hyphens, starting with a letter"
        )
    if not isinstance(cfg, dict):
        raise ConfigError(f"Project {key!r} must be a mapping")
    _require_known_keys(cfg, PROJECT_SETTINGS_KEYS | PROJECT_SECTION_KEYS, f"project {key!r}")

    settings = deep_merge(
        defaults.get("project", {}),
        {k: v for k, v in cfg.items() if k in PROJECT_SETTINGS_KEYS},
    )

    sections: dict = {}
    for section_name, entity_defaults_key in (
        ("repositories", "repository"),
        ("cleanup_policies", "cleanup_policy"),
    ):
        section = cfg.get(section_name)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise ConfigError(f"{key}.{section_name} must be a mapping")
        if section_name == "repositories" and "generate" in section:
            section = _expand_generated_repositories(key, dict(section))
        if section_name == "cleanup_policies" and "generate" in section:
            section = _expand_generated_cleanup_policies(key, dict(section))
        entity_defaults = defaults.get(entity_defaults_key, {})
        merged = {}
        for entity_name, spec in section.items():
            if entity_name == "enforce":
                merged[entity_name] = spec
                continue
            if not isinstance(spec, dict):
                raise ConfigError(f"{key}.{section_name}.{entity_name} must be a mapping")
            merged[entity_name] = deep_merge(entity_defaults, spec)
        sections[section_name] = merged

    members = cfg.get("members")
    if members is not None:
        if not isinstance(members, dict):
            raise ConfigError(f"{key}.members must be a mapping")
        unknown = set(members) - {"enforce", "users", "groups"}
        if unknown:
            raise ConfigError(
                f"Unknown keys in {key}.members: {', '.join(sorted(unknown))} (expected 'users', 'groups' or 'enforce')"
            )
        for kind in ("users", "groups"):
            if kind in members and not isinstance(members[kind], dict):
                raise ConfigError(f"{key}.members.{kind} must be a mapping of name to settings, not a list")
        sections["members"] = members

    return ProjectConfig(key=key, settings=settings, sections=sections)


def _expand_generated_repositories(project_key: str, section: dict) -> dict:
    """Expand 'generate' into concrete local repositories following the JFrog
    naming convention <team>-<tech>-<maturity>-local, one per combination of
    package type and maturity. The maturity maps to the repository's
    environment (dev -> DEV, prod -> PROD). Explicitly listed repositories
    with the same key override the generated spec."""
    generate = section.pop("generate")
    if not isinstance(generate, dict):
        raise ConfigError(f"{project_key}.repositories.generate must be a mapping")
    _require_known_keys(
        generate,
        {"package_types", "maturities"},
        f"{project_key}.repositories.generate",
    )
    package_types = _require_lowercase_list(
        generate.get("package_types"), f"{project_key}.repositories.generate.package_types"
    )
    maturities = _require_lowercase_list(generate.get("maturities"), f"{project_key}.repositories.generate.maturities")

    explicit_keys = set(section)
    generated_keys: set[str] = set()
    for package_type in package_types:
        for maturity in maturities:
            repo_key = f"{project_key}-{package_type}-{maturity}-local"
            if repo_key in generated_keys:
                raise ConfigError(
                    f"{project_key}.repositories.generate produces the key "
                    f"{repo_key!r} twice; rename a package type or maturity"
                )
            generated_keys.add(repo_key)
            generated = {
                "type": "local",
                "package_type": package_type,
                "environments": [maturity.upper()],
            }
            if repo_key in explicit_keys:
                explicit = section[repo_key]
                if not isinstance(explicit, dict):
                    raise ConfigError(f"{project_key}.repositories.{repo_key} must be a mapping")
                generated = deep_merge(generated, explicit)
            section[repo_key] = generated
    return section


def _expand_generated_cleanup_policies(project_key: str, section: dict) -> dict:
    """Expand 'generate' into concrete cleanup policies: one policy per
    combination of package type and rule, named <packageType>-<ruleName>
    (the project key prefix is added by the processor). Each rule targets
    the generated repository of its maturity
    (<project>-<packageType>-<maturity>-local). Explicitly listed policies
    with the same key override the generated spec."""
    generate = section.pop("generate")
    if not isinstance(generate, dict):
        raise ConfigError(f"{project_key}.cleanup_policies.generate must be a mapping")
    _require_known_keys(
        generate,
        {"package_types", "rules"},
        f"{project_key}.cleanup_policies.generate",
    )
    package_types = _require_lowercase_list(
        generate.get("package_types"), f"{project_key}.cleanup_policies.generate.package_types"
    )
    rules = generate.get("rules")
    if not isinstance(rules, dict) or not rules:
        raise ConfigError(
            f"{project_key}.cleanup_policies.generate.rules must be a non-empty mapping of rule name to policy settings"
        )

    explicit_keys = set(section)
    generated_keys: set[str] = set()
    for rule_name, rule in rules.items():
        if not isinstance(rule, dict):
            raise ConfigError(f"{project_key}.cleanup_policies.generate.rules.{rule_name} must be a mapping")
        maturity = rule.get("maturity")
        if not isinstance(maturity, str) or maturity != maturity.lower():
            raise ConfigError(
                f"{project_key}.cleanup_policies.generate.rules.{rule_name} needs "
                "'maturity: <lowercase maturity>' to select the target repository"
            )
        rule_spec = {k: v for k, v in rule.items() if k != "maturity"}
        for package_type in package_types:
            policy_name = f"{package_type}-{rule_name}"
            if policy_name in generated_keys:
                raise ConfigError(
                    f"{project_key}.cleanup_policies.generate produces the key "
                    f"{policy_name!r} twice; rename a package type or rule"
                )
            generated_keys.add(policy_name)
            base = {
                "search_criteria": {
                    "package_types": [package_type],
                    "repos": [f"{project_key}-{package_type}-{maturity}-local"],
                    "included_packages": ["**"],
                }
            }
            generated = deep_merge(base, rule_spec)
            # An explicit entry overrides the generated spec; both the plain
            # '<tech>-<ruleName>' key and the final prefixed policy key work.
            explicit = None
            if policy_name in explicit_keys:
                explicit = section[policy_name]
            elif (prefixed := f"{project_key}-{policy_name}") in explicit_keys:
                explicit = section.pop(prefixed)
                explicit_keys.discard(prefixed)
            if explicit is not None:
                if not isinstance(explicit, dict):
                    raise ConfigError(f"{project_key}.cleanup_policies.{policy_name} must be a mapping")
                generated = deep_merge(generated, explicit)
            section[policy_name] = generated
    return section


def _require_lowercase_list(value, where: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item == item.lower() for item in value)
    ):
        raise ConfigError(f"{where} must be a non-empty list of lowercase strings")
    return value


def _require_known_keys(mapping: dict, known: set[str], where: str) -> None:
    unknown = set(mapping) - known
    if unknown:
        raise ConfigError(
            f"Unknown keys at {where}: {', '.join(sorted(unknown))} (expected one of: {', '.join(sorted(known))})"
        )
