from typing import Any


def needs_update(current: dict, desired: dict) -> bool:
    """Asymmetric comparison: only keys present in desired are compared, so
    server-populated fields that are not managed in the config never cause
    an update."""
    for key, want in desired.items():
        if key not in current:
            return True
        have = current[key]
        if isinstance(want, dict) and isinstance(have, dict):
            if needs_update(have, want):
                return True
        elif have != want:
            return True
    return False


def changed_fields(current: dict, desired: dict, prefix: str = "") -> list[str]:
    """Human readable list of differences, following the same asymmetric
    semantics as needs_update."""
    out: list[str] = []
    for key, want in desired.items():
        path = f"{prefix}{key}"
        if key not in current:
            out.append(f"{path}: <unset> -> {_fmt(want)}")
            continue
        have = current[key]
        if isinstance(want, dict) and isinstance(have, dict):
            out.extend(changed_fields(have, want, prefix=f"{path}."))
        elif have != want:
            out.append(f"{path}: {_fmt(have)} -> {_fmt(want)}")
    return out


def _fmt(value: Any) -> str:
    text = repr(value)
    if len(text) > 120:
        text = text[:117] + "..."
    return text
