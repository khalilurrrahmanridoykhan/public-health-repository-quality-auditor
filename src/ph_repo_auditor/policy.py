from __future__ import annotations

from typing import Any

import yaml

from .models import AuditPolicy, CHECK_KEYS


def _clean_path(value: str) -> str:
    return value.strip().strip("/").lower()


def _string_list(
    source: dict[str, Any], key: str, warnings: list[str]
) -> list[str]:
    value = source.get(key, [])
    if not isinstance(value, list):
        warnings.append(f"`{key}` must be a list of paths or check keys.")
        return []
    result: list[str] = []
    for item in value[:50]:
        if not isinstance(item, str) or not item.strip():
            warnings.append(f"`{key}` contains a non-string or empty value.")
            continue
        result.append(item)
    return result


def parse_policy(content: str | None) -> tuple[AuditPolicy, tuple[str, ...]]:
    if content is None:
        return AuditPolicy(), ()
    try:
        source = yaml.safe_load(content)
    except yaml.YAMLError as error:
        return AuditPolicy(), (f"Could not parse policy YAML: {error}",)
    if source is None:
        source = {}
    if not isinstance(source, dict):
        return AuditPolicy(), (
            "Policy must be a YAML object; default policy was used.",
        )

    warnings: list[str] = []
    minimum_score = source.get("minimum_score", 80)
    if (
        not isinstance(minimum_score, int)
        or isinstance(minimum_score, bool)
        or not 0 <= minimum_score <= 100
    ):
        warnings.append("`minimum_score` must be an integer from 0 to 100.")
        minimum_score = 80

    disabled_checks: list[str] = []
    for key in _string_list(source, "disabled_checks", warnings):
        if key in CHECK_KEYS:
            disabled_checks.append(key)
        else:
            warnings.append(f"Unknown disabled check: `{key}`.")

    required_files = [
        _clean_path(path)
        for path in _string_list(source, "required_files", warnings)
    ]
    ignore_paths = [
        _clean_path(path)
        for path in _string_list(source, "ignore_paths", warnings)
    ]
    return (
        AuditPolicy(
            minimum_score=minimum_score,
            disabled_checks=tuple(dict.fromkeys(disabled_checks)),
            required_files=tuple(dict.fromkeys(required_files)),
            ignore_paths=tuple(dict.fromkeys(ignore_paths)),
        ),
        tuple(warnings),
    )
