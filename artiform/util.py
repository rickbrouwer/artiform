import re
from typing import Any

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def snake_to_camel_key(key: str) -> str:
    first, *rest = key.split("_")
    return first + "".join(part[:1].upper() + part[1:] for part in rest)


def camel_to_snake_key(key: str) -> str:
    return _CAMEL_BOUNDARY.sub("_", key).lower()


def _convert_keys(value: Any, convert) -> Any:
    if isinstance(value, dict):
        return {convert(k): _convert_keys(v, convert) for k, v in value.items()}
    if isinstance(value, list):
        return [_convert_keys(item, convert) for item in value]
    return value


def to_camel(value: Any) -> Any:
    """Recursively convert dict keys from snake_case to camelCase."""
    return _convert_keys(value, snake_to_camel_key)


def to_snake(value: Any) -> Any:
    """Recursively convert dict keys from camelCase to snake_case."""
    return _convert_keys(value, camel_to_snake_key)


def strip_nones(value: Any) -> Any:
    """Recursively remove dict entries whose value is None."""
    if isinstance(value, dict):
        return {k: strip_nones(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [strip_nones(item) for item in value]
    return value


def deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively. Dicts merge, all other values
    (including lists) are replaced by the override."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
