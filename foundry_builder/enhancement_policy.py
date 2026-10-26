#!/usr/bin/env python3
"""Политика внешних усилений и врождённых свойств предмета."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


MODULE_ID = "foundry-json-builder-enhancements"
POLICY_SCHEMA_VERSION = 7
MATERIAL_GROUP = "material_property"
CANONICAL_ENHANCEMENT_GROUPS = {
    "numeric_bonus",
    "additional_damage",
    "offensive_property",
    "defensive_property",
    "attribute_property",
    "mobility_property",
    "utility_property",
    "active_power",
    "signature_property",
}
POLICY_MODES = {"open", "restricted", "locked"}
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
POLICY_FIELDS = {
    "mode",
    "allowed_groups",
    "native_properties",
    "material_property",
    "reason",
}
NATIVE_PROPERTY_FIELDS = {"group", "name", "description"}
MATERIAL_PROPERTY_FIELDS = {"id", "name", "benefits"}


class EnhancementPolicyError(Exception):
    """Политику усилений предмета нельзя безопасно нормализовать."""


def _reject_unknown_fields(
    source: dict[str, Any],
    allowed: set[str],
    path: str,
) -> None:
    unknown = sorted(set(source) - allowed)
    if unknown:
        raise EnhancementPolicyError(
            f"{path} содержит неподдерживаемые поля: {', '.join(unknown)}."
        )


def _require_text(value: Any, path: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise EnhancementPolicyError(f"{path} не должен быть пустым.")
    return result


def _require_group(value: Any, path: str) -> str:
    group = str(value or "").strip()
    if group not in CANONICAL_ENHANCEMENT_GROUPS:
        raise EnhancementPolicyError(
            f"{path} должен быть одной из канонических групп: "
            + ", ".join(sorted(CANONICAL_ENHANCEMENT_GROUPS))
            + "."
        )
    return group


def _group_list(value: Any, path: str) -> list[str]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise EnhancementPolicyError(f"{path} должен быть массивом.")
    groups = [
        _require_group(group, f"{path}[{index}]")
        for index, group in enumerate(value)
    ]
    if len(groups) != len(set(groups)):
        raise EnhancementPolicyError(f"{path} содержит повторяющиеся группы.")
    return groups


def _normalize_native_properties(
    value: Any,
    path: str,
) -> list[dict[str, str]]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise EnhancementPolicyError(f"{path} должен быть массивом.")
    result: list[dict[str, str]] = []
    groups: set[str] = set()
    for index, entry in enumerate(value):
        entry_path = f"{path}[{index}]"
        if not isinstance(entry, dict):
            raise EnhancementPolicyError(f"{entry_path} должен быть объектом.")
        _reject_unknown_fields(entry, NATIVE_PROPERTY_FIELDS, entry_path)
        group = _require_group(entry.get("group"), f"{entry_path}.group")
        if group in groups:
            raise EnhancementPolicyError(
                f"{path} содержит несколько записей группы {group}. "
                "Объедините врождённые свойства этой группы в одну запись."
            )
        groups.add(group)
        result.append(
            {
                "group": group,
                "name": _require_text(entry.get("name"), f"{entry_path}.name"),
                "description": _require_text(
                    entry.get("description"),
                    f"{entry_path}.description",
                ),
            }
        )
    return result


def _normalize_material_property(
    value: Any,
    path: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise EnhancementPolicyError(f"{path} должен быть объектом или null.")
    _reject_unknown_fields(value, MATERIAL_PROPERTY_FIELDS, path)
    material_id = str(value.get("id") or "").strip()
    if not ID_PATTERN.fullmatch(material_id):
        raise EnhancementPolicyError(
            f"{path}.id должен соответствовать [a-z][a-z0-9_]{{2,63}}."
        )
    benefits = value.get("benefits")
    if (
        not isinstance(benefits, list)
        or not benefits
        or any(not isinstance(benefit, str) or not benefit.strip() for benefit in benefits)
    ):
        raise EnhancementPolicyError(
            f"{path}.benefits должен содержать минимум одно непустое описание."
        )
    normalized_benefits = [benefit.strip() for benefit in benefits]
    if len(normalized_benefits) != len(
        {benefit.casefold() for benefit in normalized_benefits}
    ):
        raise EnhancementPolicyError(f"{path}.benefits содержит повторы.")
    return {
        "group": MATERIAL_GROUP,
        "id": material_id,
        "name": _require_text(value.get("name"), f"{path}.name"),
        "benefits": normalized_benefits,
    }


def validate_policy(
    value: Any,
    path: str = "$.enhancement_policy",
) -> dict[str, Any]:
    """Проверяет исходную политику и создаёт runtime-метаданные."""
    if not isinstance(value, dict):
        raise EnhancementPolicyError(f"{path} должен быть объектом.")
    source = deepcopy(value)
    _reject_unknown_fields(source, POLICY_FIELDS, path)

    mode = str(source.get("mode") or "").strip()
    if mode not in POLICY_MODES:
        raise EnhancementPolicyError(
            f"{path}.mode должен быть одним из: "
            + ", ".join(sorted(POLICY_MODES))
            + "."
        )
    native_properties = _normalize_native_properties(
        source.get("native_properties"),
        f"{path}.native_properties",
    )
    reserved_groups = [entry["group"] for entry in native_properties]
    allowed_groups = _group_list(
        source.get("allowed_groups"),
        f"{path}.allowed_groups",
    )
    overlap = sorted(set(reserved_groups).intersection(allowed_groups))
    if overlap:
        raise EnhancementPolicyError(
            f"{path}: зарезервированные врождёнными свойствами группы нельзя "
            "одновременно разрешать: "
            + ", ".join(overlap)
            + "."
        )
    if mode == "restricted" and not allowed_groups:
        raise EnhancementPolicyError(
            f"{path}.allowed_groups для restricted не должен быть пустым."
        )
    if mode != "restricted" and allowed_groups:
        raise EnhancementPolicyError(
            f"{path}.allowed_groups используется только при mode=restricted."
        )

    reason = str(source.get("reason") or "").strip()
    if mode == "locked" and not reason:
        raise EnhancementPolicyError(
            f"{path}.reason обязателен для mode=locked."
        )

    return {
        "schemaVersion": POLICY_SCHEMA_VERSION,
        "mode": mode,
        "reservedGroups": reserved_groups,
        "allowedGroups": allowed_groups,
        "nativeProperties": native_properties,
        "materialProperty": _normalize_material_property(
            source.get("material_property"),
            f"{path}.material_property",
        ),
        "reason": reason,
    }


def _artifact_fallback_policy(item_name: str) -> dict[str, Any]:
    return validate_policy(
        {
            "mode": "locked",
            "allowed_groups": [],
            "native_properties": [],
            "material_property": None,
            "reason": (
                "Артефакт не содержит явной политики усилений. "
                "Для безопасности внешние усиления запрещены."
            ),
        },
        f"{item_name}.enhancement_policy",
    )


def _open_fallback_policy() -> dict[str, Any]:
    return validate_policy(
        {
            "mode": "open",
            "allowed_groups": [],
            "native_properties": [],
            "material_property": None,
            "reason": "",
        }
    )


def apply_item_policy(
    item: dict[str, Any],
    report: Any,
    path: str,
) -> None:
    """Переносит enhancement_policy в защищённые флаги Item."""
    flags = item.setdefault("flags", {})
    if not isinstance(flags, dict):
        raise EnhancementPolicyError(f"{path}.flags должен быть объектом.")
    namespace = flags.setdefault(MODULE_ID, {})
    if not isinstance(namespace, dict):
        raise EnhancementPolicyError(
            f"{path}.flags.{MODULE_ID} должен быть объектом."
        )

    raw_policy = item.pop("enhancement_policy", None)
    existing = namespace.get("itemPolicy")
    if raw_policy is not None:
        policy = validate_policy(raw_policy, f"{path}.enhancement_policy")
        action = "compiled_enhancement_policy"
    elif isinstance(existing, dict):
        return
    else:
        system = item.get("system")
        rarity = (
            str(system.get("rarity") or "").casefold().strip()
            if isinstance(system, dict)
            else ""
        )
        if rarity == "artifact":
            policy = _artifact_fallback_policy(str(item.get("name") or "Артефакт"))
            action = "locked_artifact_without_explicit_policy"
            warning = getattr(report, "warning", None)
            if callable(warning):
                warning(
                    f"{item.get('name')}: артефакт без enhancement_policy "
                    "автоматически закрыт для внешних усилений."
                )
        else:
            policy = _open_fallback_policy()
            action = "defaulted_open_enhancement_policy"

    namespace["itemPolicy"] = policy
    change = getattr(report, "change", None)
    if callable(change):
        change(
            f"{path}.flags.{MODULE_ID}.itemPolicy",
            action,
            existing,
            deepcopy(policy),
        )
