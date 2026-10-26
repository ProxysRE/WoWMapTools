#!/usr/bin/env python3
"""Проверка и компиляция одного штатного D&D5e Enchantment."""

from __future__ import annotations

import hashlib
import html
import json
import re
from copy import deepcopy
from typing import Any

import feat_builder
import project_config


MODULE_ID = "foundry-json-builder-enhancements"
SCHEMA_VERSION = 7
SUPPORTED_SCHEMA_VERSIONS = {1, 2, 3, 4, 5, 6, 7}
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
DOCUMENT_ID = re.compile(r"^[A-Za-z0-9]{16}$")

CANONICAL_GROUPS = {
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
ENHANCEMENT_RANKS = {"standard", "exceptional", "unique", "artifact"}
SIGNATURE_GROUP = "signature_property"
SUPPORT_CHANGE_KEYS = {
    "name",
    "img",
    "system.properties",
    "system.proficient",
    "system.description.value",
    "system.uses.max",
    "system.uses.recovery",
}
CHANGE_KEY_GROUPS = {
    "system.magicalBonus": "numeric_bonus",
    "system.armor.magicalBonus": "numeric_bonus",
    "system.damage.parts": "additional_damage",
    "system.damage.bonus": "additional_damage",
    "system.damage.base.types": "additional_damage",
    "system.damage.types": "additional_damage",
    "system.range.value": "offensive_property",
    "system.range.long": "offensive_property",
    "activities[attack].attack.ability": "offensive_property",
    "activities[attack].attack.bonus": "offensive_property",
    "activities[attack].attack.flat": "offensive_property",
    "activities[attack].attack.critical.threshold": "offensive_property",
    "activities[save].save.dc.bonus": "offensive_property",
    "activities[save].save.dc.calculation": "offensive_property",
    "activities[save].save.dc.formula": "offensive_property",
}

MODE_IDS = {
    "multiply": 1,
    "add": 2,
    "downgrade": 3,
    "upgrade": 4,
    "override": 5,
}

CHANGE_RULES = {
    "name": {"override"},
    "img": {"override"},
    "system.properties": {"add"},
    "system.proficient": {"upgrade"},
    "system.magicalBonus": {"override"},
    "system.armor.magicalBonus": {"override"},
    "system.damage.parts": {"add"},
    "system.damage.bonus": set(MODE_IDS),
    "system.damage.base.types": {"add", "override"},
    "system.damage.types": {"add", "override"},
    "system.range.value": {"multiply"},
    "system.range.long": {"multiply"},
    "system.description.value": {"add", "override"},
    "system.uses.max": {"override"},
    "system.uses.recovery": {"add"},
    "activities[attack].attack.ability": {"override"},
    "activities[attack].attack.bonus": {"override"},
    "activities[attack].attack.flat": {"override"},
    "activities[attack].attack.critical.threshold": {"downgrade"},
    "activities[save].save.dc.bonus": set(MODE_IDS),
    "activities[save].save.dc.calculation": {"override"},
    "activities[save].save.dc.formula": {"override"},
}
ALLOWED_CHANGE_KEYS = set(CHANGE_RULES)
ENHANCEMENT_FIELDS = {
    "id",
    "name",
    "img",
    "group",
    "tier",
    "rank",
    "occupies_groups",
    "signature_benefits",
    "attunement",
    "description",
    "manual",
    "changes",
    "riders",
}
ATTUNEMENT_FIELDS = {"weight", "required"}
CHANGE_FIELDS = {"key", "mode", "value"}
RIDER_FIELDS = {"activities", "effects", "items"}
RIDER_ACTIVITY_FIELDS = {
    "type",
    "activity_name",
    "attack",
    "save",
    "damage",
    "on_save",
    "healing",
    "roll",
    "activation",
    "duration",
    "targeting",
    "description",
    "chat_flavor",
    "midi_properties",
    "auto_target_action",
    "auto_target_type",
    "friendly_save",
    "effect_condition_text",
    "use_condition_text",
    "use_condition_reason",
    "uses",
    "unlimited",
    "is_over_time",
    "over_time_properties",
}
RIDER_USES_FIELDS = {"max", "spent", "recovery"}
RIDER_RECOVERY_FIELDS = {"period", "type"}
RIDER_EFFECT_FIELDS = {
    "name",
    "img",
    "status",
    "statuses",
    "changes",
    "disabled",
    "duration",
    "description",
    "origin",
    "tint",
    "transfer",
    "activity",
    "activities",
    "on_save",
    "level_min",
    "level_max",
    "sort",
    "dae",
    "special_duration",
}
RIDER_EFFECT_CHANGE_FIELDS = {"key", "mode", "value", "priority"}
RIDER_ACTIVITY_TYPES = {"attack", "save", "damage", "heal", "utility"}
ABILITY_IDS = {"str", "dex", "con", "int", "wis", "cha", ""}
MULTI_CHANGE_KEYS = {"system.properties", "system.uses.recovery"}

DAMAGE_TYPES = {
    "acid",
    "bludgeoning",
    "cold",
    "fire",
    "force",
    "lightning",
    "necrotic",
    "piercing",
    "poison",
    "psychic",
    "radiant",
    "slashing",
    "thunder",
}


class EnhancementBuilderError(Exception):
    """Исходное усиление нельзя безопасно скомпилировать."""


def stable_id(namespace: str, machine_id: str) -> str:
    """Возвращает стабильный 16-символьный Foundry ID."""
    value = hashlib.sha256(f"{namespace}:{machine_id}".encode("utf-8")).hexdigest()
    return value[:16]


def _require_id(value: Any, path: str) -> str:
    result = str(value or "").strip()
    if not ID_PATTERN.fullmatch(result):
        raise EnhancementBuilderError(
            f"{path} должен соответствовать [a-z][a-z0-9_]{{2,63}}."
        )
    return result


def _require_text(value: Any, path: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise EnhancementBuilderError(f"{path} не должен быть пустым.")
    return result


def _encode_change_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _validate_damage_parts(value: Any, path: str) -> None:
    if not isinstance(value, list) or not value:
        raise EnhancementBuilderError(
            f"{path} для system.damage.parts должен быть непустым массивом."
        )
    for index, part in enumerate(value):
        if (
            not isinstance(part, list)
            or len(part) != 2
            or not str(part[0] or "").strip()
            or str(part[1] or "") not in DAMAGE_TYPES
        ):
            raise EnhancementBuilderError(
                f"{path}[{index}] должен иметь вид [\"1d4\", \"fire\"]."
            )


def _reject_unknown_fields(
    source: dict[str, Any],
    allowed: set[str],
    path: str,
) -> None:
    unknown = sorted(set(source) - allowed)
    if unknown:
        raise EnhancementBuilderError(
            f"{path} содержит неподдерживаемые поля: {', '.join(unknown)}."
        )


def _require_schema_version(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EnhancementBuilderError(
            "schema_version должен быть целым числом."
        )
    if value not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(str(item) for item in sorted(SUPPORTED_SCHEMA_VERSIONS))
        raise EnhancementBuilderError(
            f"schema_version должен быть одним из: {supported}."
        )
    return value


def _validate_rider_activity(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EnhancementBuilderError(f"{path} должен быть объектом.")
    result = deepcopy(value)
    _reject_unknown_fields(result, RIDER_ACTIVITY_FIELDS, path)
    activity_type = str(result.get("type") or "").casefold().strip()
    if activity_type not in RIDER_ACTIVITY_TYPES:
        raise EnhancementBuilderError(
            f"{path}.type должен быть одним из: "
            + ", ".join(sorted(RIDER_ACTIVITY_TYPES))
            + "."
        )
    result["type"] = activity_type
    result["activity_name"] = _require_text(
        result.get("activity_name"), f"{path}.activity_name"
    )

    uses = result.get("uses")
    unlimited = result.get("unlimited")
    if uses is not None:
        if not isinstance(uses, dict):
            raise EnhancementBuilderError(f"{path}.uses должен быть объектом.")
        _reject_unknown_fields(uses, RIDER_USES_FIELDS, f"{path}.uses")
        maximum = str(uses.get("max") or "").strip()
        if not maximum:
            raise EnhancementBuilderError(
                f"{path}.uses.max не должен быть пустым."
            )
        spent = uses.get("spent", 0)
        if isinstance(spent, bool) or not isinstance(spent, int) or spent < 0:
            raise EnhancementBuilderError(
                f"{path}.uses.spent должен быть целым числом от 0."
            )
        recovery = uses.get("recovery", [])
        if not isinstance(recovery, list):
            raise EnhancementBuilderError(
                f"{path}.uses.recovery должен быть массивом."
            )
        normalized_recovery: list[dict[str, str]] = []
        for index, entry in enumerate(recovery):
            entry_path = f"{path}.uses.recovery[{index}]"
            if not isinstance(entry, dict):
                raise EnhancementBuilderError(
                    f"{entry_path} должен быть объектом."
                )
            _reject_unknown_fields(entry, RIDER_RECOVERY_FIELDS, entry_path)
            period = str(entry.get("period") or "").strip()
            recovery_type = str(entry.get("type") or "").strip()
            if not period or not recovery_type:
                raise EnhancementBuilderError(
                    f"{entry_path} должен содержать period и type."
                )
            normalized_recovery.append(
                {"period": period, "type": recovery_type}
            )
        result["uses"] = {
            "max": maximum,
            "spent": spent,
            "recovery": normalized_recovery,
        }
        if unlimited not in (None, False):
            raise EnhancementBuilderError(
                f"{path}: uses и unlimited нельзя задавать одновременно."
            )
        result.pop("unlimited", None)
    else:
        if unlimited is not True:
            raise EnhancementBuilderError(
                f"{path}: активная rider-activity должна содержать uses "
                "либо явное unlimited: true."
            )
        result["unlimited"] = True

    activation = result.get("activation")
    if not isinstance(activation, dict):
        raise EnhancementBuilderError(f"{path}.activation должен быть объектом.")
    if not str(activation.get("type") or "").strip():
        raise EnhancementBuilderError(
            f"{path}.activation.type не должен быть пустым."
        )

    targeting = result.get("targeting")
    if not isinstance(targeting, dict):
        raise EnhancementBuilderError(f"{path}.targeting должен быть объектом.")
    range_data = targeting.get("range")
    affects = targeting.get("affects")
    if not isinstance(range_data, dict) or not str(
        range_data.get("units") or ""
    ).strip():
        raise EnhancementBuilderError(
            f"{path}.targeting.range.units не должен быть пустым."
        )
    if not isinstance(affects, dict) or not str(
        affects.get("type") or ""
    ).strip():
        raise EnhancementBuilderError(
            f"{path}.targeting.affects.type не должен быть пустым."
        )

    if activity_type == "attack" and not isinstance(result.get("attack"), dict):
        raise EnhancementBuilderError(f"{path}.attack должен быть объектом.")
    if activity_type == "save" and not isinstance(result.get("save"), dict):
        raise EnhancementBuilderError(f"{path}.save должен быть объектом.")
    if activity_type == "damage" and not isinstance(result.get("damage"), list):
        raise EnhancementBuilderError(f"{path}.damage должен быть массивом.")
    if activity_type == "heal" and not isinstance(result.get("healing"), dict):
        raise EnhancementBuilderError(f"{path}.healing должен быть объектом.")
    if activity_type == "utility" and "roll" in result and not isinstance(
        result.get("roll"), dict
    ):
        raise EnhancementBuilderError(f"{path}.roll должен быть объектом.")
    return result


def _validate_rider_effect(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EnhancementBuilderError(f"{path} должен быть объектом.")
    result = deepcopy(value)
    _reject_unknown_fields(result, RIDER_EFFECT_FIELDS, path)
    result["name"] = _require_text(result.get("name"), f"{path}.name")
    transfer = result.get("transfer")
    if not isinstance(transfer, bool):
        raise EnhancementBuilderError(f"{path}.transfer должен быть true или false.")
    if transfer and (
        result.get("activity") not in (None, "")
        or result.get("activities") not in (None, "", [])
    ):
        raise EnhancementBuilderError(
            f"{path}: постоянный transfer-эффект владельца не должен "
            "ссылаться на activity."
        )
    if not transfer and (
        result.get("activity") in (None, "")
        and result.get("activities") in (None, "", [])
    ):
        raise EnhancementBuilderError(
            f"{path}: применяемый эффект должен явно указать activity "
            "или activities."
        )

    changes = result.get("changes", [])
    if not isinstance(changes, list):
        raise EnhancementBuilderError(f"{path}.changes должен быть массивом.")
    normalized_changes: list[dict[str, Any]] = []
    for index, change in enumerate(changes):
        change_path = f"{path}.changes[{index}]"
        if not isinstance(change, dict):
            raise EnhancementBuilderError(f"{change_path} должен быть объектом.")
        _reject_unknown_fields(change, RIDER_EFFECT_CHANGE_FIELDS, change_path)
        key = str(change.get("key") or "").strip()
        if not key.startswith("system."):
            raise EnhancementBuilderError(
                f"{change_path}.key должен быть путём system.* актёра."
            )
        mode = change.get("mode", "add")
        if isinstance(mode, bool):
            raise EnhancementBuilderError(f"{change_path}.mode некорректен.")
        if isinstance(mode, int):
            if mode not in MODE_IDS.values() and mode != 0:
                raise EnhancementBuilderError(
                    f"{change_path}.mode должен быть целым числом от 0 до 5."
                )
        elif str(mode).casefold().strip() not in {
            "custom",
            *MODE_IDS.keys(),
        }:
            raise EnhancementBuilderError(
                f"{change_path}.mode содержит неизвестный режим."
            )
        if "value" not in change:
            raise EnhancementBuilderError(f"{change_path}.value отсутствует.")
        normalized_changes.append(deepcopy(change))
    result["changes"] = normalized_changes

    statuses = result.get("statuses", result.get("status"))
    has_status = bool(
        str(statuses or "").strip()
        if not isinstance(statuses, list)
        else any(str(item or "").strip() for item in statuses)
    )
    if not normalized_changes and not has_status:
        raise EnhancementBuilderError(
            f"{path} должен содержать changes, status или statuses."
        )
    return result


def _validate_change_value(key: str, value: Any, path: str) -> None:
    if key == "system.damage.parts":
        _validate_damage_parts(value, path)
    elif key in {"system.damage.base.types", "system.damage.types"}:
        values = value if isinstance(value, list) else [value]
        if not values or any(str(item) not in DAMAGE_TYPES for item in values):
            raise EnhancementBuilderError(
                f"{path} должен содержать поддерживаемые английские типы урона."
            )
    elif key in {
        "system.magicalBonus",
        "system.armor.magicalBonus",
        "activities[attack].attack.critical.threshold",
    }:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise EnhancementBuilderError(f"{path} должен быть числом.")
        try:
            numeric = int(value)
        except (TypeError, ValueError) as error:
            raise EnhancementBuilderError(f"{path} должен быть целым числом.") from error
        if key.endswith("critical.threshold") and numeric < 1:
            raise EnhancementBuilderError(f"{path} должен быть целым числом от 1.")
    elif key == "activities[attack].attack.flat":
        if not isinstance(value, bool):
            raise EnhancementBuilderError(f"{path} должен быть true или false.")
    elif key == "activities[attack].attack.ability":
        if str(value) not in ABILITY_IDS:
            raise EnhancementBuilderError(
                f"{path} должен быть одним из: {', '.join(sorted(ABILITY_IDS))}."
            )
    elif key == "system.uses.recovery":
        if not isinstance(value, dict):
            raise EnhancementBuilderError(f"{path} должен быть объектом recovery.")
        if not str(value.get("period") or "").strip():
            raise EnhancementBuilderError(f"{path}.period не должен быть пустым.")
        if not str(value.get("type") or "").strip():
            raise EnhancementBuilderError(f"{path}.type не должен быть пустым.")
    elif key == "system.properties":
        if not isinstance(value, str) or not value.strip():
            raise EnhancementBuilderError(
                f"{path} должен быть непустым системным идентификатором свойства."
            )
    elif key in {
        "name",
        "img",
        "system.description.value",
        "system.damage.bonus",
        "system.range.value",
        "system.range.long",
        "system.uses.max",
        "activities[attack].attack.bonus",
        "activities[save].save.dc.bonus",
        "activities[save].save.dc.formula",
    }:
        if not str(value).strip():
            raise EnhancementBuilderError(f"{path} не должен быть пустым.")


def validate_document(source: Any) -> dict[str, Any]:
    """Проверяет корневой формат одного усиления."""
    if not isinstance(source, dict):
        raise EnhancementBuilderError("Корень JSON должен быть объектом.")
    unknown = sorted(set(source) - {"schema_version", "type", "enhancement"})
    if unknown:
        raise EnhancementBuilderError(
            "Корень enhancement содержит неподдерживаемые поля: "
            + ", ".join(unknown)
            + "."
        )
    schema_version = _require_schema_version(source.get("schema_version"))
    if source.get("type") != "enhancement":
        raise EnhancementBuilderError('type должен быть "enhancement".')
    result = deepcopy(source)
    result["schema_version"] = schema_version
    result["enhancement"] = validate_enhancement(
        result.get("enhancement"),
        schema_version=schema_version,
    )
    return result


def validate_enhancement(
    source: Any,
    path: str = "$.enhancement",
    *,
    schema_version: int = SCHEMA_VERSION,
) -> dict[str, Any]:
    """Проверяет и нормализует одну запись каталога."""
    if not isinstance(source, dict):
        raise EnhancementBuilderError(f"{path} должен быть объектом.")

    result = deepcopy(source)
    _reject_unknown_fields(result, ENHANCEMENT_FIELDS, path)
    result["id"] = _require_id(result.get("id"), f"{path}.id")
    result["name"] = _require_text(result.get("name"), f"{path}.name")
    result["group"] = _require_id(result.get("group"), f"{path}.group")
    if schema_version >= 5 and result["group"] not in CANONICAL_GROUPS:
        raise EnhancementBuilderError(
            f"{path}.group должен быть одной из канонических групп: "
            + ", ".join(sorted(CANONICAL_GROUPS))
            + "."
        )
    result["description"] = _require_text(
        result.get("description"), f"{path}.description"
    )
    result["manual"] = str(result.get("manual") or "").strip()
    result["img"] = str(
        result.get("img")
        or "icons/magic/symbols/runes-star-pentagon-blue.webp"
    )

    tier = result.get("tier")
    if isinstance(tier, bool) or not isinstance(tier, int) or tier < 1:
        raise EnhancementBuilderError(f"{path}.tier должен быть целым числом от 1.")
    result["tier"] = tier

    if schema_version >= 5:
        rank = str(result.get("rank") or "").strip()
        if rank not in ENHANCEMENT_RANKS:
            raise EnhancementBuilderError(
                f"{path}.rank должен быть одним из: "
                + ", ".join(sorted(ENHANCEMENT_RANKS))
                + "."
            )
        raw_occupied = result.get("occupies_groups")
        if raw_occupied is None:
            occupied = [result["group"]]
        elif (
            not isinstance(raw_occupied, list)
            or not raw_occupied
            or any(
                not isinstance(group, str) or group not in CANONICAL_GROUPS
                for group in raw_occupied
            )
            or len(raw_occupied) != len(set(raw_occupied))
        ):
            raise EnhancementBuilderError(
                f"{path}.occupies_groups должен быть непустым массивом "
                "уникальных канонических групп."
            )
        else:
            occupied = list(raw_occupied)
        if result["group"] not in occupied:
            raise EnhancementBuilderError(
                f"{path}.occupies_groups должен содержать основную группу "
                f"{result['group']}."
            )
        if result["group"] != SIGNATURE_GROUP and occupied != [result["group"]]:
            raise EnhancementBuilderError(
                f"{path}: занимать несколько групп может только "
                f"{SIGNATURE_GROUP}."
            )
        if result["group"] == SIGNATURE_GROUP and rank == "standard":
            raise EnhancementBuilderError(
                f"{path}: signature_property не может иметь ранг standard."
            )
        if schema_version >= 6 and occupied != [result["group"]]:
            raise EnhancementBuilderError(
                f"{path}: начиная со schema_version 6 усиление занимает "
                "только собственную группу. signature_property является "
                "отдельным дополнительным слотом и не блокирует обычные группы."
            )
        result["rank"] = rank
        result["occupies_groups"] = occupied
    else:
        if "rank" in result or "occupies_groups" in result:
            raise EnhancementBuilderError(
                f"{path}.rank и occupies_groups поддерживаются только "
                "начиная со schema_version 5."
            )

    if "attunement" in result:
        if schema_version < 4:
            raise EnhancementBuilderError(
                f"{path}.attunement поддерживается только начиная "
                "со schema_version 4."
            )
        attunement = result["attunement"]
        if not isinstance(attunement, dict):
            raise EnhancementBuilderError(
                f"{path}.attunement должен быть объектом."
            )
        _reject_unknown_fields(
            attunement,
            ATTUNEMENT_FIELDS,
            f"{path}.attunement",
        )
        weight = attunement.get("weight", 0)
        if (
            isinstance(weight, bool)
            or not isinstance(weight, int)
            or weight < 0
            or weight > 4
        ):
            raise EnhancementBuilderError(
                f"{path}.attunement.weight должен быть целым числом от 0 до 4."
            )
        required = attunement.get("required", False)
        if not isinstance(required, bool):
            raise EnhancementBuilderError(
                f"{path}.attunement.required должен быть true или false."
            )
        result["attunement"] = {
            "weight": weight,
            "required": required,
        }
    elif schema_version >= 4:
        result["attunement"] = {
            "weight": 0,
            "required": False,
        }

    raw_changes = result.get("changes")
    if not isinstance(raw_changes, list):
        raise EnhancementBuilderError(f"{path}.changes должен быть массивом.")
    changes: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for index, change in enumerate(raw_changes):
        change_path = f"{path}.changes[{index}]"
        if not isinstance(change, dict):
            raise EnhancementBuilderError(f"{change_path} должен быть объектом.")
        _reject_unknown_fields(change, CHANGE_FIELDS, change_path)
        key = str(change.get("key") or "").strip()
        mode = str(change.get("mode") or "").strip().casefold()
        if key not in ALLOWED_CHANGE_KEYS:
            raise EnhancementBuilderError(
                f"{change_path}.key «{key}» отсутствует в разрешённом реестре."
            )
        if mode not in MODE_IDS:
            raise EnhancementBuilderError(
                f"{change_path}.mode должен быть одним из: "
                + ", ".join(MODE_IDS)
                + "."
            )
        allowed_modes = CHANGE_RULES[key]
        if mode not in allowed_modes:
            raise EnhancementBuilderError(
                f"{change_path}.mode для {key} должен быть одним из: "
                + ", ".join(sorted(allowed_modes))
                + "."
            )
        if "value" not in change:
            raise EnhancementBuilderError(f"{change_path}.value отсутствует.")
        if key in seen_keys and key not in MULTI_CHANGE_KEYS:
            raise EnhancementBuilderError(
                f"{change_path}.key повторяется: {key}. Объедините изменение."
            )
        seen_keys.add(key)
        value = deepcopy(change["value"])
        _validate_change_value(key, value, f"{change_path}.value")
        changes.append({"key": key, "mode": mode, "value": value})
    result["changes"] = changes

    riders = result.get("riders")
    if not isinstance(riders, dict):
        raise EnhancementBuilderError(f"{path}.riders должен быть объектом.")
    _reject_unknown_fields(riders, RIDER_FIELDS, f"{path}.riders")
    normalized_riders: dict[str, list[Any]] = {}
    for key in ("activities", "effects", "items"):
        value = riders.get(key)
        if not isinstance(value, list):
            raise EnhancementBuilderError(f"{path}.riders.{key} должен быть массивом.")
        if key == "activities":
            normalized_riders[key] = [
                _validate_rider_activity(
                    item,
                    f"{path}.riders.activities[{index}]",
                )
                for index, item in enumerate(value)
            ]
        elif key == "effects":
            normalized_riders[key] = [
                _validate_rider_effect(
                    item,
                    f"{path}.riders.effects[{index}]",
                )
                for index, item in enumerate(value)
            ]
        else:
            normalized_riders[key] = deepcopy(value)
    result["riders"] = normalized_riders

    if schema_version == 1 and any(normalized_riders.values()):
        raise EnhancementBuilderError(
            f"{path}.riders зарезервирован, но в schema_version 1 принимает "
            "только пустые массивы."
        )
    if schema_version >= 2 and normalized_riders["items"]:
        raise EnhancementBuilderError(
            f"{path}.riders.items зарезервирован и в schema_version 2 "
            "должен быть пустым массивом."
        )
    if normalized_riders["effects"] and not normalized_riders["activities"]:
        if any(
            not effect.get("transfer", False)
            for effect in normalized_riders["effects"]
        ):
            raise EnhancementBuilderError(
                f"{path}.riders.effects содержит применяемый эффект, "
                "но riders.activities пуст."
            )
    if schema_version >= 6:
        raw_signature_benefits = result.get("signature_benefits")
        if result["group"] == SIGNATURE_GROUP:
            if (
                not isinstance(raw_signature_benefits, list)
                or len(raw_signature_benefits) < 2
                or any(
                    not isinstance(benefit, str) or not benefit.strip()
                    for benefit in raw_signature_benefits
                )
            ):
                raise EnhancementBuilderError(
                    f"{path}.signature_benefits для signature_property должен "
                    "быть массивом минимум из двух непустых описаний уникальных "
                    "эффектов."
                )
            signature_benefits = [
                benefit.strip() for benefit in raw_signature_benefits
            ]
            if len(signature_benefits) != len(
                {benefit.casefold() for benefit in signature_benefits}
            ):
                raise EnhancementBuilderError(
                    f"{path}.signature_benefits содержит повторяющиеся эффекты."
                )
            result["signature_benefits"] = signature_benefits
            substantive_keys = [
                key
                for key in seen_keys
                if key not in SUPPORT_CHANGE_KEYS and key in CHANGE_KEY_GROUPS
            ]
            if substantive_keys:
                raise EnhancementBuilderError(
                    f"{path}: signature_property не должно состоять из обычных "
                    "числовых бонусов, дополнительных костей урона или иных "
                    "стандартных изменений предмета."
                )
        elif raw_signature_benefits is not None:
            raise EnhancementBuilderError(
                f"{path}.signature_benefits разрешён только для "
                "signature_property."
            )
    elif "signature_benefits" in result:
        raise EnhancementBuilderError(
            f"{path}.signature_benefits поддерживается только начиная "
            "со schema_version 6."
        )

    if schema_version >= 5 and result["group"] != SIGNATURE_GROUP:
        substantive_groups = {
            CHANGE_KEY_GROUPS[key]
            for key in seen_keys
            if key not in SUPPORT_CHANGE_KEYS and key in CHANGE_KEY_GROUPS
        }
        if len(substantive_groups) > 1:
            raise EnhancementBuilderError(
                f"{path}: обычное усиление содержит свойства нескольких "
                "канонических групп."
            )
        if substantive_groups and substantive_groups != {result["group"]}:
            actual = next(iter(substantive_groups))
            raise EnhancementBuilderError(
                f"{path}: механика группы {actual} не может находиться в "
                f"обычной группе {result['group']}."
            )
        if substantive_groups and (
            normalized_riders["activities"] or normalized_riders["effects"]
        ):
            raise EnhancementBuilderError(
                f"{path}: обычное усиление не может одновременно изменять "
                "предмет и добавлять самостоятельные rider-механики."
            )
        if len(normalized_riders["activities"]) > 1:
            raise EnhancementBuilderError(
                f"{path}: обычное усиление может содержать не более одной "
                "rider-activity."
            )
        if len(normalized_riders["effects"]) > 1:
            raise EnhancementBuilderError(
                f"{path}: обычное усиление может содержать не более одного "
                "rider-эффекта."
            )
        if normalized_riders["activities"] and any(
            effect.get("transfer") is True
            for effect in normalized_riders["effects"]
        ):
            raise EnhancementBuilderError(
                f"{path}: обычное усиление не может одновременно содержать "
                "активную способность и постоянный переносимый эффект."
            )
    has_mechanics = bool(changes) or any(normalized_riders.values())
    if not has_mechanics and not result["manual"]:
        raise EnhancementBuilderError(
            f"{path} не содержит changes, riders или ручной части manual."
        )
    return result


def build_rider_documents(
    source: dict[str, Any],
    *,
    set_id: str,
    schema_version: int = SCHEMA_VERSION,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Компилирует дополнительные activities и Active Effects Enchantment."""
    enhancement = validate_enhancement(
        source,
        schema_version=schema_version,
    )
    rider_source = enhancement["riders"]
    activity_specs = deepcopy(rider_source["activities"])
    effect_specs = deepcopy(rider_source["effects"])
    for index, activity in enumerate(activity_specs):
        activity["_id"] = stable_id(
            f"{set_id}:{enhancement['id']}:rider-activity",
            str(index),
        )
    for index, effect in enumerate(effect_specs):
        effect["_id"] = stable_id(
            f"{set_id}:{enhancement['id']}:rider-effect",
            str(index),
        )

    mechanics = {
        "activities": activity_specs,
        "effects": effect_specs,
    }
    report = feat_builder.BuildReport(
        source=f"enhancement:{enhancement['id']}"
    )
    activities = feat_builder._build_activities(
        mechanics,
        enhancement["name"],
        report,
    )
    effects = feat_builder._build_effects(
        mechanics,
        activities,
        enhancement["name"],
        report,
    )
    if report.warnings:
        raise EnhancementBuilderError(
            f"Усиление {enhancement['id']}: rider не прошёл компиляцию: "
            + "; ".join(report.warnings)
        )
    if len(activities) != len(activity_specs):
        raise EnhancementBuilderError(
            f"Усиление {enhancement['id']}: создано {len(activities)} rider "
            f"activities вместо {len(activity_specs)}."
        )
    if len(effects) != len(effect_specs):
        raise EnhancementBuilderError(
            f"Усиление {enhancement['id']}: создано {len(effects)} rider "
            f"effects вместо {len(effect_specs)}."
        )
    return activities, effects


def _active_effect_changes(enhancement: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "key": change["key"],
            "mode": MODE_IDS[change["mode"]],
            "value": _encode_change_value(change["value"]),
            "priority": None,
        }
        for change in enhancement["changes"]
    ]


def build_enchantment_effect(
    source: dict[str, Any],
    *,
    set_id: str,
    effect_id: str | None = None,
    rider_ids: dict[str, list[str]] | None = None,
    schema_version: int = SCHEMA_VERSION,
) -> dict[str, Any]:
    """Создаёт Active Effect типа enchantment для профиля Enchant."""
    enhancement = validate_enhancement(
        source,
        schema_version=schema_version,
    )
    resolved_effect_id = effect_id or stable_id(
        f"{set_id}:effect", enhancement["id"]
    )
    if not DOCUMENT_ID.fullmatch(resolved_effect_id):
        raise EnhancementBuilderError("effect_id должен содержать 16 символов.")

    riders = rider_ids or {"activity": [], "effect": [], "item": []}
    normalized_riders = {
        key: list(riders.get(key, []))
        for key in ("activity", "effect", "item")
    }
    metadata = {
        "id": enhancement["id"],
        "group": enhancement["group"],
        "tier": enhancement["tier"],
        "setId": set_id,
    }
    if schema_version >= 4:
        metadata["attunement"] = deepcopy(
            enhancement.get("attunement")
            or {"weight": 0, "required": False}
        )
    if schema_version >= 5:
        metadata["rank"] = enhancement["rank"]
        metadata["occupiesGroups"] = deepcopy(
            enhancement["occupies_groups"]
        )
    if schema_version >= 6:
        metadata["schemaVersion"] = schema_version
        if enhancement["group"] == SIGNATURE_GROUP:
            metadata["signatureBenefits"] = deepcopy(
                enhancement["signature_benefits"]
            )
    attunement = enhancement.get("attunement") or {
        "weight": 0,
        "required": False,
    }
    attunement_description = (
        f"<p><strong>Настройка:</strong> вес {attunement['weight']}"
        + ("; требуется самостоятельно." if attunement["required"] else ".")
        + "</p>"
        if schema_version >= 4
        else ""
    )
    return {
        "_id": resolved_effect_id,
        "name": enhancement["name"],
        "type": "enchantment",
        "img": enhancement["img"],
        "system": {},
        "changes": _active_effect_changes(enhancement),
        "disabled": True,
        "duration": {
            "startTime": None,
            "seconds": None,
            "combat": None,
            "rounds": None,
            "turns": None,
            "startRound": None,
            "startTurn": None,
        },
        "description": (
            f"<p>{html.escape(enhancement['description'])}</p>"
            + (
                f"<p><strong>Вручную:</strong> "
                f"{html.escape(enhancement['manual'])}</p>"
                if enhancement["manual"]
                else ""
            )
            + f"<p><strong>Группа:</strong> "
            f"{html.escape(enhancement['group'])}; "
            f"<strong>тир:</strong> T{enhancement['tier']}.</p>"
            + (
                f"<p><strong>Ранг:</strong> "
                f"{html.escape(enhancement['rank'])}; "
                f"<strong>занимает группы:</strong> "
                f"{html.escape(', '.join(enhancement['occupies_groups']))}.</p>"
                if schema_version >= 5
                else ""
            )
            + (
                "<p><strong>Особые эффекты:</strong> "
                + "; ".join(
                    html.escape(benefit)
                    for benefit in enhancement["signature_benefits"]
                )
                + ".</p>"
                if schema_version >= 6
                and enhancement["group"] == SIGNATURE_GROUP
                else ""
            )
            + attunement_description
        ),
        "origin": None,
        "tint": "#ffffff",
        "transfer": True,
        "statuses": [],
        "sort": 0,
        "flags": {
            "dnd5e": {
                "enchantment": {
                    "level": {"min": None, "max": None},
                    "riders": normalized_riders,
                }
            },
            MODULE_ID: {"enhancement": metadata},
        },
        "_stats": {
            "compendiumSource": None,
            "duplicateSource": None,
            "coreVersion": project_config.EXPORT_CORE_VERSION,
            "systemId": "dnd5e",
            "systemVersion": project_config.DND5E_VERSION,
            "createdTime": None,
            "modifiedTime": None,
            "lastModifiedBy": None,
            "exportSource": None,
        },
    }


def build_catalog_item(
    source: dict[str, Any],
    *,
    set_id: str,
    document_id: str | None = None,
    schema_version: int = SCHEMA_VERSION,
) -> dict[str, Any]:
    """Создаёт читаемый Item каталога, на который ссылается RollTable."""
    enhancement = validate_enhancement(
        source,
        schema_version=schema_version,
    )
    resolved_id = document_id or stable_id(f"{set_id}:catalog", enhancement["id"])
    description = (
        f"<h2>{html.escape(enhancement['name'])}</h2>"
        f"<p>{html.escape(enhancement['description'])}</p>"
        f"<p><strong>Группа:</strong> {html.escape(enhancement['group'])}; "
        f"<strong>тир:</strong> T{enhancement['tier']}.</p>"
    )
    if schema_version >= 5:
        description += (
            f"<p><strong>Ранг:</strong> {html.escape(enhancement['rank'])}; "
            f"<strong>занимает группы:</strong> "
            f"{html.escape(', '.join(enhancement['occupies_groups']))}.</p>"
        )
    if schema_version >= 6 and enhancement["group"] == SIGNATURE_GROUP:
        description += (
            "<p><strong>Особые эффекты:</strong> "
            + "; ".join(
                html.escape(benefit)
                for benefit in enhancement["signature_benefits"]
            )
            + ".</p>"
        )
    if schema_version >= 4:
        attunement = enhancement["attunement"]
        description += (
            f"<p><strong>Настройка:</strong> вес {attunement['weight']}"
            + (
                "; требуется самостоятельно."
                if attunement["required"]
                else "."
            )
            + "</p>"
        )
    if enhancement["manual"]:
        description += (
            f"<p><strong>Ручная часть:</strong> "
            f"{html.escape(enhancement['manual'])}</p>"
        )
    return {
        "_id": resolved_id,
        "name": enhancement["name"],
        "type": "feat",
        "img": enhancement["img"],
        "system": {
            "activities": {},
            "uses": {"spent": 0, "recovery": []},
            "advancement": {},
            "description": {"value": description, "chat": ""},
            "identifier": enhancement["id"].replace("_", "-"),
            "source": {"revision": 1, "rules": "2024"},
            "crewed": False,
            "enchant": {},
            "prerequisites": {"items": [], "repeatable": False},
            "properties": [],
            "requirements": f"Усиление T{enhancement['tier']}",
            "type": {"value": "feat", "subtype": ""},
        },
        "effects": [],
        "folder": None,
        "flags": {
            MODULE_ID: {
                "catalog": {
                    "id": enhancement["id"],
                    "group": enhancement["group"],
                    "tier": enhancement["tier"],
                    "rank": enhancement.get("rank", "standard"),
                    "occupiesGroups": deepcopy(
                        enhancement.get("occupies_groups")
                        or [enhancement["group"]]
                    ),
                    "schemaVersion": schema_version,
                    "signatureBenefits": deepcopy(
                        enhancement.get("signature_benefits") or []
                    ),
                    "attunement": deepcopy(
                        enhancement.get("attunement")
                        or {"weight": 0, "required": False}
                    ),
                    "setId": set_id,
                }
            }
        },
        "_stats": {
            "coreVersion": project_config.EXPORT_CORE_VERSION,
            "systemId": "dnd5e",
            "systemVersion": project_config.DND5E_VERSION,
            "createdTime": 0,
            "modifiedTime": 0,
            "lastModifiedBy": None,
            "exportSource": None,
        },
    }


def build_bundle_catalog_item(
    source: dict[str, Any],
    components: list[dict[str, Any]],
    *,
    set_id: str,
    document_id: str,
) -> dict[str, Any]:
    """Создаёт читаемую запись каталога для составного усиления."""
    component_list = "".join(
        f"<li><strong>{html.escape(component['name'])}</strong> "
        f"({html.escape(component['group'])}) — "
        f"{html.escape(component['description'])}</li>"
        for component in components
    )
    description = (
        f"<h2>{html.escape(source['name'])}</h2>"
        f"<p>{html.escape(source['description'])}</p>"
        f"<p><strong>Составное усиление:</strong> при одном применении "
        f"накладывает {len(components)} независимых усиления разных групп.</p>"
        f"<ol>{component_list}</ol>"
        f"<p><strong>Тир:</strong> T{source['tier']}.</p>"
    )
    attunement_weight = sum(
        int(component.get("attunement", {}).get("weight", 0))
        for component in components
    )
    attunement_required = any(
        component.get("attunement", {}).get("required") is True
        for component in components
    )
    description += (
        f"<p><strong>Настройка:</strong> суммарный вес {attunement_weight}"
        + ("; требуется самостоятельно." if attunement_required else ".")
        + "</p>"
    )
    return {
        "_id": document_id,
        "name": source["name"],
        "type": "feat",
        "img": source["img"],
        "system": {
            "activities": {},
            "uses": {"spent": 0, "recovery": []},
            "advancement": {},
            "description": {"value": description, "chat": ""},
            "identifier": source["id"].replace("_", "-"),
            "source": {"revision": 1, "rules": "2024"},
            "crewed": False,
            "enchant": {},
            "prerequisites": {"items": [], "repeatable": False},
            "properties": [],
            "requirements": f"Составное усиление T{source['tier']}",
            "type": {"value": "feat", "subtype": ""},
        },
        "effects": [],
        "folder": None,
        "flags": {
            MODULE_ID: {
                "catalog": {
                    "id": source["id"],
                    "kind": "bundle",
                    "enhancementIds": [
                        component["id"] for component in components
                    ],
                    "groups": [
                        component["group"] for component in components
                    ],
                    "tier": source["tier"],
                    "attunement": {
                        "weight": attunement_weight,
                        "required": attunement_required,
                    },
                    "setId": set_id,
                }
            }
        },
        "_stats": {
            "coreVersion": project_config.EXPORT_CORE_VERSION,
            "systemId": "dnd5e",
            "systemVersion": project_config.DND5E_VERSION,
            "createdTime": 0,
            "modifiedTime": 0,
            "lastModifiedBy": None,
            "exportSource": None,
        },
    }
