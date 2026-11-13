#!/usr/bin/env python3
"""Билдер классов персонажей Foundry VTT.

Целевая связка:
    Foundry VTT 13.351
    D&D5e 5.3.3

Поддерживаются два входных формата:
1. полный экспорт Item типа ``class`` из Foundry;
2. компактный авторский JSON, описанный в ``AI_CLASS_SUBCLASS_JSON_GUIDE.md``.

Примеры запуска:
    python class_builder.py class_input.json
    python class_builder.py class_input.json -o class_foundry.json
    python class_builder.py class_input.json --report build_report.json

Подключён к общему приложению builder_app.py и character_builder.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


import project_config

FOUNDRY_CORE_VERSION = project_config.EXPORT_CORE_VERSION
DND5E_SYSTEM_VERSION = project_config.DND5E_VERSION
ABILITY_KEYS = {"str", "dex", "con", "int", "wis", "cha"}
HIT_DICE = {"d4", "d6", "d8", "d10", "d12"}
SPELLCASTING_PROGRESSIONS = {
    "none",
    "full",
    "half",
    "third",
    "pact",
    "artificer",
}
ADVANCEMENT_TYPES = {
    "HitPoints",
    "Subclass",
    "AbilityScoreImprovement",
    "Trait",
    "ItemGrant",
    "ItemChoice",
    "ScaleValue",
    "Size",
}
ADVANCEMENT_ALIASES = {
    "hitpoints": "HitPoints",
    "hit_points": "HitPoints",
    "hp": "HitPoints",
    "subclass": "Subclass",
    "asi": "AbilityScoreImprovement",
    "abilityscoreimprovement": "AbilityScoreImprovement",
    "ability_score_improvement": "AbilityScoreImprovement",
    "trait": "Trait",
    "itemgrant": "ItemGrant",
    "item_grant": "ItemGrant",
    "grant": "ItemGrant",
    "itemchoice": "ItemChoice",
    "item_choice": "ItemChoice",
    "choice": "ItemChoice",
    "scalevalue": "ScaleValue",
    "scale_value": "ScaleValue",
    "scale": "ScaleValue",
    "size": "Size",
}
DOCUMENT_ID = re.compile(r"^[A-Za-z0-9]{16}$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]*$")
UUID_PREFIXES = ("Compendium.", "Item.")


class ClassBuilderError(Exception):
    """Ошибка, после которой нельзя создать надёжный Item класса."""


@dataclass
class Change:
    path: str
    action: str
    old: Any = None
    new: Any = None


@dataclass
class BuildReport:
    source: str = ""
    output: str = ""
    class_name: str = ""
    input_format: str = ""
    identifier: str = ""
    advancement_types: dict[str, int] = field(default_factory=dict)
    changes: list[Change] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def change(self, path: str, action: str, old: Any, new: Any) -> None:
        self.changes.append(Change(path, action, old, new))

    def warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


def _stable_id(*parts: Any) -> str:
    payload = "\x1f".join(
        json.dumps(part, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for part in parts
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "kh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "shch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


def _slugify(value: str) -> str:
    transliterated = value.strip().lower().translate(_TRANSLIT)
    slug = re.sub(r"[^a-z0-9]+", "-", transliterated).strip("-")
    return slug or f"custom-class-{_stable_id(value)[:8]}"


def _int(value: Any, path: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ClassBuilderError(f"{path}: ожидалось целое число.")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ClassBuilderError(f"{path}: ожидалось целое число.") from exc
    if result < minimum or result > maximum:
        raise ClassBuilderError(
            f"{path}: значение {result} вне диапазона {minimum}–{maximum}."
        )
    return result


def _as_dict(value: Any, path: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ClassBuilderError(f"{path}: ожидался объект JSON.")
    return deepcopy(value)


def _as_list(value: Any, path: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ClassBuilderError(f"{path}: ожидался массив JSON.")
    return deepcopy(value)


def _source(value: Any, compact: dict[str, Any]) -> dict[str, Any]:
    result = _as_dict(value, "source")
    result.setdefault("revision", compact.get("revision", 1))
    result.setdefault("rules", compact.get("rules", "2024"))
    result["revision"] = _int(result["revision"], "source.revision", 1, 999)
    result["rules"] = str(result["rules"] or "2024")
    return result


def _description(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            "value": str(value.get("value", "")),
            "chat": str(value.get("chat", "")),
        }
    return {"value": "" if value is None else str(value), "chat": ""}


def _spell_defaults() -> dict[str, Any]:
    return {
        "ability": [""],
        "uses": {"max": "", "per": "", "requireSlot": False},
        "prepared": 0,
    }


def _normalize_choice_levels(value: Any, path: str, minimum_level: int = 1) -> dict[str, dict[str, Any]]:
    if isinstance(value, list):
        value = {str(level): {"count": 1, "replacement": False} for level in value}
    if not isinstance(value, dict) or not value:
        raise ClassBuilderError(f"{path}: нужен непустой объект уровней выбора.")
    result: dict[str, dict[str, Any]] = {}
    for raw_level, raw_config in value.items():
        level = _int(raw_level, f"{path}.{raw_level}", minimum_level, 20)
        config = _as_dict(raw_config, f"{path}.{raw_level}")
        count = config.get("count", 1)
        if count is not None:
            count = _int(count, f"{path}.{raw_level}.count", 0, 99)
        result[str(level)] = {
            "count": count,
            "replacement": bool(config.get("replacement", False)),
        }
    return dict(sorted(result.items(), key=lambda pair: int(pair[0])))


def _normalize_pool(value: Any, path: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, entry in enumerate(_as_list(value, path)):
        item = {"uuid": entry} if isinstance(entry, str) else _as_dict(
            entry, f"{path}[{index}]"
        )
        uuid = str(item.get("uuid", "")).strip()
        if not uuid:
            raise ClassBuilderError(f"{path}[{index}].uuid: UUID не указан.")
        item["uuid"] = uuid
        result.append(item)
    return result


def _normalize_grant_items(value: Any, path: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, entry in enumerate(_as_list(value, path)):
        item = {"uuid": entry} if isinstance(entry, str) else _as_dict(
            entry, f"{path}[{index}]"
        )
        uuid = str(item.get("uuid", "")).strip()
        if not uuid:
            raise ClassBuilderError(f"{path}[{index}].uuid: UUID не указан.")
        if not uuid.startswith(UUID_PREFIXES):
            raise ClassBuilderError(
                f"{path}[{index}].uuid: ожидается Compendium.… или Item.…"
            )
        result.append({"uuid": uuid, "optional": bool(item.get("optional", False))})
    if not result:
        raise ClassBuilderError(f"{path}: ItemGrant должен выдавать хотя бы один Item.")
    return result


def _advancement_type(value: Any, path: str) -> str:
    raw = str(value or "").strip()
    if raw in ADVANCEMENT_TYPES:
        return raw
    normalized = re.sub(r"[\s-]+", "_", raw).lower()
    result = ADVANCEMENT_ALIASES.get(normalized)
    if not result:
        raise ClassBuilderError(
            f"{path}: неподдерживаемый тип развития {raw!r}."
        )
    return result


def _common_advancement(
    raw: dict[str, Any],
    advancement_type: str,
    advancement_id: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "_id": advancement_id,
        "type": advancement_type,
        "configuration": {},
        "value": {},
    }
    if advancement_type not in {"HitPoints"}:
        result["title"] = str(raw.get("title", ""))
        if "icon" in raw:
            result["icon"] = raw.get("icon")
    result["flags"] = _as_dict(raw.get("flags"), "advancement.flags")
    result["hint"] = str(raw.get("hint", ""))
    return result


def _build_advancement(
    raw_value: Any,
    index: int,
    class_identifier: str,
    *, minimum_level: int = 1,
) -> dict[str, Any]:
    raw = _as_dict(raw_value, f"advancement[{index}]")
    advancement_type = _advancement_type(
        raw.get("type"), f"advancement[{index}].type"
    )
    level_seed = raw.get("level", raw.get("levels"))
    advancement_id = str(raw.get("_id", "")).strip()
    if not DOCUMENT_ID.fullmatch(advancement_id):
        advancement_id = _stable_id(
            class_identifier,
            advancement_type,
            index,
            raw.get("title", ""),
            level_seed,
        )
    result = _common_advancement(raw, advancement_type, advancement_id)

    if advancement_type == "Size":
        config = _as_dict(raw.get("configuration"), "size.configuration")
        sizes = _as_list(config.get("sizes", raw.get("sizes", ["med"])), "size.sizes")
        if not sizes or any(not isinstance(size, str) or size not in {"tiny", "sm", "med", "lg", "huge", "grg"} for size in sizes):
            raise ClassBuilderError("size.sizes: неизвестный или пустой список размеров.")
        result["configuration"] = {"sizes": list(dict.fromkeys(sizes))}
        return result

    if advancement_type == "HitPoints":
        return result

    if advancement_type == "Subclass":
        result["level"] = _int(raw.get("level", 3), "subclass.level", 1, 20)
        value = _as_dict(raw.get("value"), "subclass.value")
        result["value"] = {
            "document": value.get("document"),
            "uuid": value.get("uuid"),
        }
        return result

    if advancement_type == "AbilityScoreImprovement":
        result["level"] = _int(raw.get("level"), "asi.level", minimum_level, 20)
        config = _as_dict(raw.get("configuration"), "asi.configuration")
        fixed = _as_dict(config.get("fixed", raw.get("fixed")), "asi.fixed")
        normalized_fixed = {
            ability: _int(fixed.get(ability, 0), f"asi.fixed.{ability}", -30, 30)
            for ability in sorted(ABILITY_KEYS)
        }
        locked = [
            ability
            for ability in _as_list(
                config.get("locked", raw.get("locked")), "asi.locked"
            )
            if ability in ABILITY_KEYS
        ]
        cap = config.get("cap", raw.get("cap", 2))
        if cap is not None:
            cap = _int(cap, "asi.cap", 1, 30)
        result["configuration"] = {
            "points": _int(
                config.get("points", raw.get("points", 2)), "asi.points", 0, 30
            ),
            "fixed": normalized_fixed,
            "cap": cap,
            "locked": locked,
            "recommendation": config.get(
                "recommendation", raw.get("recommendation")
            ),
        }
        value = _as_dict(raw.get("value"), "asi.value")
        result["value"] = {"type": value.get("type", "asi")}
        return result

    if advancement_type == "Trait":
        result["level"] = _int(raw.get("level", 1), "trait.level", minimum_level, 20)
        config = _as_dict(raw.get("configuration"), "trait.configuration")
        grants = config.get("grants", raw.get("grants", []))
        choices = config.get("choices", raw.get("choices", []))
        result["configuration"] = {
            "mode": str(config.get("mode", raw.get("mode", "default"))),
            "allowReplacements": bool(
                config.get(
                    "allowReplacements",
                    raw.get("allow_replacements", raw.get("allowReplacements", False)),
                )
            ),
            "grants": [str(value) for value in _as_list(grants, "trait.grants")],
            "choices": _as_list(choices, "trait.choices"),
        }
        chosen = _as_dict(raw.get("value"), "trait.value").get(
            "chosen", raw.get("chosen", [])
        )
        result["value"] = {"chosen": _as_list(chosen, "trait.chosen")}
        restriction = raw.get("classRestriction", raw.get("class_restriction"))
        if restriction is not None:
            restriction = str(restriction)
            if restriction not in {"primary", "secondary"}:
                raise ClassBuilderError(
                    "trait.class_restriction: допустимы primary или secondary."
                )
            result["classRestriction"] = restriction
        return result

    if advancement_type == "ItemGrant":
        result["level"] = _int(raw.get("level", 1), "item_grant.level", minimum_level, 20)
        config = _as_dict(raw.get("configuration"), "item_grant.configuration")
        result["configuration"] = {
            "items": _normalize_grant_items(
                config.get("items", raw.get("items")),
                "item_grant.items",
            ),
            "optional": bool(config.get("optional", raw.get("optional", False))),
            "spell": _as_dict(
                config.get("spell", raw.get("spell", _spell_defaults())),
                "item_grant.spell",
            ),
        }
        result["configuration"]["spell"] = {
            **_spell_defaults(),
            **result["configuration"]["spell"],
        }
        return result

    if advancement_type == "ItemChoice":
        config = _as_dict(raw.get("configuration"), "item_choice.configuration")
        pool = _normalize_pool(
            config.get("pool", raw.get("pool", [])), "item_choice.pool"
        )
        allow_drops = bool(
            config.get("allowDrops", raw.get("allow_drops", raw.get("allowDrops", True)))
        )
        if not pool and not allow_drops:
            raise ClassBuilderError(
                "item_choice: нужен pool либо allow_drops: true."
            )
        item_type = config.get("type", raw.get("item_type", raw.get("itemType")))
        result["configuration"] = {
            "choices": _normalize_choice_levels(
                config.get("choices", raw.get("choices")),
                "item_choice.choices",
                minimum_level,
            ),
            "allowDrops": allow_drops,
            "type": item_type,
            "pool": pool,
            "spell": {
                **_spell_defaults(),
                **_as_dict(
                    config.get("spell", raw.get("spell", {})),
                    "item_choice.spell",
                ),
            },
            "restriction": _as_dict(
                config.get("restriction", raw.get("restriction", {})),
                "item_choice.restriction",
            ),
        }
        value = _as_dict(raw.get("value"), "item_choice.value")
        result["value"] = {
            "added": _as_dict(value.get("added"), "item_choice.value.added"),
            "replaced": _as_dict(
                value.get("replaced"), "item_choice.value.replaced"
            ),
        }
        return result

    if advancement_type == "ScaleValue":
        config = _as_dict(raw.get("configuration"), "scale.configuration")
        identifier = str(config.get("identifier", raw.get("identifier", ""))).strip()
        if not IDENTIFIER.fullmatch(identifier):
            raise ClassBuilderError(
                "scale.identifier: нужен уникальный идентификатор из a-z, 0-9 и '-'."
            )
        scale_type = str(config.get("type", raw.get("scale_type", raw.get("scaleType", "number"))))
        if scale_type not in {"number", "string", "dice", "distance"}:
            raise ClassBuilderError(
                "scale.scale_type: допустимы number, string, dice или distance."
            )
        scale = _as_dict(config.get("scale", raw.get("scale")), "scale.scale")
        normalized_scale: dict[str, Any] = {}
        for raw_level, entry in scale.items():
            level = _int(raw_level, f"scale.scale.{raw_level}", 1, 20)
            normalized_scale[str(level)] = deepcopy(entry)
        if not normalized_scale:
            raise ClassBuilderError("scale.scale: таблица прогрессии пуста.")
        result["configuration"] = {
            "identifier": identifier,
            "type": scale_type,
            "distance": _as_dict(
                config.get("distance", raw.get("distance", {"units": ""})),
                "scale.distance",
            ),
            "scale": dict(
                sorted(normalized_scale.items(), key=lambda pair: int(pair[0]))
            ),
        }
        return result

    raise AssertionError(f"Необработанный тип {advancement_type}")


def _native_advancement(
    raw_value: Any,
    key: str,
    index: int,
    class_identifier: str,
    report: BuildReport,
) -> tuple[str, dict[str, Any]]:
    raw = _as_dict(raw_value, f"system.advancement.{key}")
    advancement_type = _advancement_type(
        raw.get("type"), f"system.advancement.{key}.type"
    )
    advancement_id = str(raw.get("_id", key)).strip()
    if not DOCUMENT_ID.fullmatch(advancement_id):
        replacement = _stable_id(
            class_identifier,
            advancement_type,
            index,
            raw.get("title", ""),
            raw.get("level"),
        )
        report.change(
            f"system.advancement.{key}._id",
            "generated_stable_id",
            advancement_id,
            replacement,
        )
        advancement_id = replacement
    raw["_id"] = advancement_id
    raw["type"] = advancement_type
    raw.setdefault("configuration", {})
    raw.setdefault("value", {})
    raw.setdefault("flags", {})
    raw.setdefault("hint", "")
    return advancement_id, raw


def _validate_advancement(
    advancement: dict[str, dict[str, Any]],
    report: BuildReport,
    *,
    allow_blank_scale_identifier: bool = False,
    document_type: str = "class",
) -> None:
    minimum_level = 0 if document_type in {"race", "feat", "background"} else 1
    ids: set[str] = set()
    subclass_count = 0
    hit_points_count = 0
    scale_identifiers: set[str] = set()
    asi_levels: list[int] = []
    forbidden = {
        "race": {"HitPoints", "Subclass", "ScaleValue"},
        "feat": {"HitPoints", "Subclass", "ScaleValue", "Size"},
        "background": {"HitPoints", "Subclass", "ScaleValue", "Size"},
        "subclass": {"HitPoints", "Subclass", "Size", "AbilityScoreImprovement"},
        "class": {"Size"},
    }

    for key, entry in advancement.items():
        advancement_id = str(entry.get("_id", ""))
        if advancement_id != key:
            raise ClassBuilderError(
                f"system.advancement.{key}: ключ должен совпадать с _id."
            )
        if advancement_id in ids:
            raise ClassBuilderError(f"Повторяющийся advancement _id: {advancement_id}.")
        ids.add(advancement_id)
        advancement_type = _advancement_type(
            entry.get("type"), f"system.advancement.{key}.type"
        )
        if advancement_type in forbidden[document_type]:
            raise ClassBuilderError(f"{document_type} не может содержать {advancement_type}.")
        if not DOCUMENT_ID.fullmatch(advancement_id):
            raise ClassBuilderError(f"Некорректный advancement _id: {advancement_id}.")
        if advancement_type == "HitPoints":
            hit_points_count += 1
        elif advancement_type == "Subclass":
            subclass_count += 1
            _int(entry.get("level"), f"system.advancement.{key}.level", 1, 20)
        elif advancement_type == "AbilityScoreImprovement":
            asi_levels.append(
                _int(entry.get("level"), f"system.advancement.{key}.level", minimum_level, 20)
            )
        elif advancement_type in {"Trait", "ItemGrant"}:
            _int(entry.get("level"), f"system.advancement.{key}.level", minimum_level, 20)
            if advancement_type == "ItemGrant":
                _normalize_grant_items(entry.get("configuration", {}).get("items"), f"system.advancement.{key}.items")
        elif advancement_type == "ItemChoice":
            config = _as_dict(
                entry.get("configuration"),
                f"system.advancement.{key}.configuration",
            )
            _normalize_choice_levels(
                config.get("choices"),
                f"system.advancement.{key}.configuration.choices",
                minimum_level,
            )
        elif advancement_type == "ScaleValue":
            config = _as_dict(
                entry.get("configuration"),
                f"system.advancement.{key}.configuration",
            )
            scale_identifier = str(config.get("identifier", "")).strip()
            if not scale_identifier:
                if allow_blank_scale_identifier:
                    report.warning(
                        f"system.advancement.{key}: ScaleValue без identifier; "
                        "полный экспорт сохранён без изменения."
                    )
                    continue
                raise ClassBuilderError(
                    f"system.advancement.{key}: ScaleValue без identifier."
                )
            if scale_identifier in scale_identifiers:
                raise ClassBuilderError(
                    f"Повторяющийся ScaleValue identifier: {scale_identifier}."
                )
            scale_identifiers.add(scale_identifier)

    if hit_points_count == 0 and document_type == "class":
        report.warning("В классе отсутствует HitPoints advancement.")
    elif hit_points_count > 1:
        raise ClassBuilderError("В классе не может быть несколько HitPoints.")
    if subclass_count > 1:
        raise ClassBuilderError("В классе не может быть несколько Subclass advancement.")
    duplicates = sorted(level for level, count in Counter(asi_levels).items() if count > 1)
    if duplicates:
        report.warning(
            "Несколько повышений характеристик находятся на одном уровне: "
            + ", ".join(map(str, duplicates))
            + "."
        )

    report.advancement_types = dict(
        sorted(Counter(entry["type"] for entry in advancement.values()).items())
    )


def _build_compact(data: dict[str, Any], report: BuildReport) -> dict[str, Any]:
    compact = _as_dict(data.get("class", data), "class")
    name = str(compact.get("name", "")).strip()
    if not name:
        raise ClassBuilderError("name: название класса обязательно.")
    identifier = str(compact.get("identifier", "")).strip().lower()
    if not identifier:
        identifier = _slugify(name)
        report.change("system.identifier", "generated_identifier", None, identifier)
    if not IDENTIFIER.fullmatch(identifier):
        raise ClassBuilderError(
            "identifier: нужны строчные a-z, цифры и дефисы; первый символ — буква или цифра."
        )

    hit_die = str(
        compact.get(
            "hit_die",
            _as_dict(compact.get("hd"), "hd").get("denomination", "d8"),
        )
    ).lower()
    if hit_die not in HIT_DICE:
        raise ClassBuilderError(
            f"hit_die: {hit_die!r} не поддерживается; допустимы {sorted(HIT_DICE)}."
        )

    spellcasting = _as_dict(compact.get("spellcasting"), "spellcasting")
    progression = str(spellcasting.get("progression", "none")).lower()
    if progression not in SPELLCASTING_PROGRESSIONS:
        raise ClassBuilderError(
            "spellcasting.progression: неподдерживаемая прогрессия "
            f"{progression!r}."
        )
    spell_ability = str(spellcasting.get("ability", "")).lower()
    if spell_ability and spell_ability not in ABILITY_KEYS:
        raise ClassBuilderError(
            "spellcasting.ability: допустимы str, dex, con, int, wis, cha или пусто."
        )

    primary = compact.get("primary_abilities", compact.get("primaryAbility", []))
    primary_all = bool(compact.get("primary_all", False))
    if isinstance(primary, dict):
        primary_all = bool(primary.get("all", primary_all))
        primary = primary.get("value", [])
    primary_values = [str(value).lower() for value in _as_list(primary, "primary_abilities")]
    invalid_primary = sorted(set(primary_values) - ABILITY_KEYS)
    if invalid_primary:
        raise ClassBuilderError(
            "primary_abilities: неизвестные характеристики "
            + ", ".join(invalid_primary)
            + "."
        )

    raw_advancements = _as_list(compact.get("advancement"), "advancement")
    if not any(
        _advancement_type(entry.get("type"), "advancement.type") == "HitPoints"
        for entry in raw_advancements
        if isinstance(entry, dict)
    ):
        raw_advancements.insert(0, {"type": "hit_points"})
        report.change(
            "system.advancement",
            "added_required_hit_points",
            None,
            "HitPoints",
        )

    advancement: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_advancements):
        entry = _build_advancement(raw, index, identifier)
        advancement_id = entry["_id"]
        if advancement_id in advancement:
            raise ClassBuilderError(
                f"advancement[{index}]: повторяющийся _id {advancement_id}."
            )
        advancement[advancement_id] = entry

    preparation = _as_dict(
        spellcasting.get("preparation"), "spellcasting.preparation"
    )
    preparation.setdefault("formula", "")
    system = {
        "advancement": advancement,
        "description": _description(compact.get("description")),
        "identifier": identifier,
        "source": _source(compact.get("source"), compact),
        "startingEquipment": _as_list(
            compact.get("starting_equipment", compact.get("startingEquipment")),
            "starting_equipment",
        ),
        "wealth": str(compact.get("wealth", "")),
        "hd": {
            "denomination": hit_die,
            "spent": _int(
                _as_dict(compact.get("hd"), "hd").get(
                    "spent", compact.get("hit_dice_spent", 0)
                ),
                "hd.spent",
                0,
                20,
            ),
            "additional": str(
                _as_dict(compact.get("hd"), "hd").get("additional", "")
            ),
        },
        "levels": _int(compact.get("levels", 1), "levels", 1, 20),
        "primaryAbility": {"value": primary_values, "all": primary_all},
        "properties": [
            str(value) for value in _as_list(compact.get("properties"), "properties")
        ],
        "spellcasting": {
            "progression": progression,
            "ability": spell_ability,
            "preparation": preparation,
        },
    }
    result = {
        "name": name,
        "type": "class",
        "img": str(
            compact.get("img", "systems/dnd5e/icons/svg/items/class.svg")
        ),
        "system": system,
        "effects": _as_list(compact.get("effects"), "effects"),
        "folder": compact.get("folder"),
        "flags": _as_dict(compact.get("flags"), "flags"),
        "_stats": {
            "compendiumSource": None,
            "duplicateSource": None,
            "coreVersion": FOUNDRY_CORE_VERSION,
            "systemId": "dnd5e",
            "systemVersion": DND5E_SYSTEM_VERSION,
        },
        "ownership": _as_dict(
            compact.get("ownership", {"default": 0}), "ownership"
        ),
    }
    _validate_advancement(advancement, report)
    report.class_name = name
    report.identifier = identifier
    report.input_format = "compact"
    return result


def _normalize_native(data: dict[str, Any], report: BuildReport) -> dict[str, Any]:
    result = deepcopy(data)
    if result.get("type") != "class":
        raise ClassBuilderError("Полный экспорт должен иметь type: \"class\".")
    name = str(result.get("name", "")).strip()
    if not name:
        raise ClassBuilderError("name: название класса обязательно.")
    system = _as_dict(result.get("system"), "system")
    result["system"] = system

    identifier = str(system.get("identifier", "")).strip().lower()
    if not identifier:
        identifier = _slugify(name)
        system["identifier"] = identifier
        report.change("system.identifier", "generated_identifier", None, identifier)
    if not IDENTIFIER.fullmatch(identifier):
        raise ClassBuilderError(
            "system.identifier: нужны строчные a-z, цифры и дефисы."
        )
    if identifier.endswith("-"):
        report.warning(
            f"Идентификатор {identifier!r} оканчивается дефисом; Foundry его сохраняет, "
            "но для новых классов лучше использовать стабильный идентификатор без дефиса."
        )

    system["description"] = _description(system.get("description"))
    system["source"] = _source(system.get("source"), system)
    system.setdefault("startingEquipment", [])
    system.setdefault("wealth", "")
    system.setdefault("properties", [])
    system["levels"] = _int(system.get("levels", 1), "system.levels", 1, 20)

    hd = _as_dict(system.get("hd"), "system.hd")
    denomination = str(hd.get("denomination", "d8")).lower()
    if denomination not in HIT_DICE:
        raise ClassBuilderError(
            f"system.hd.denomination: {denomination!r} не поддерживается."
        )
    hd["denomination"] = denomination
    hd["spent"] = _int(hd.get("spent", 0), "system.hd.spent", 0, 20)
    hd["additional"] = str(hd.get("additional", ""))
    system["hd"] = hd

    primary = _as_dict(system.get("primaryAbility"), "system.primaryAbility")
    primary["value"] = [
        str(value).lower()
        for value in _as_list(primary.get("value"), "system.primaryAbility.value")
    ]
    invalid_primary = sorted(set(primary["value"]) - ABILITY_KEYS)
    if invalid_primary:
        raise ClassBuilderError(
            "system.primaryAbility.value: неизвестные характеристики "
            + ", ".join(invalid_primary)
            + "."
        )
    primary["all"] = bool(primary.get("all", False))
    system["primaryAbility"] = primary

    spellcasting = _as_dict(system.get("spellcasting"), "system.spellcasting")
    progression = str(spellcasting.get("progression", "none")).lower()
    if progression not in SPELLCASTING_PROGRESSIONS:
        raise ClassBuilderError(
            f"system.spellcasting.progression: {progression!r} не поддерживается."
        )
    ability = str(spellcasting.get("ability", "")).lower()
    if ability and ability not in ABILITY_KEYS:
        raise ClassBuilderError(
            f"system.spellcasting.ability: неизвестная характеристика {ability!r}."
        )
    spellcasting["progression"] = progression
    spellcasting["ability"] = ability
    spellcasting["preparation"] = _as_dict(
        spellcasting.get("preparation"), "system.spellcasting.preparation"
    )
    spellcasting["preparation"].setdefault("formula", "")
    system["spellcasting"] = spellcasting

    raw_advancement = _as_dict(system.get("advancement"), "system.advancement")
    advancement: dict[str, dict[str, Any]] = {}
    for index, (key, raw) in enumerate(raw_advancement.items()):
        advancement_id, entry = _native_advancement(
            raw, key, index, identifier, report
        )
        if advancement_id in advancement:
            raise ClassBuilderError(
                f"system.advancement: повторяющийся _id {advancement_id}."
            )
        advancement[advancement_id] = entry
    system["advancement"] = advancement

    result.setdefault("img", "systems/dnd5e/icons/svg/items/class.svg")
    result.setdefault("effects", [])
    result.setdefault("folder", None)
    result.setdefault("flags", {})
    result.setdefault("ownership", {"default": 0})
    stats = _as_dict(result.get("_stats"), "_stats")
    stats["coreVersion"] = FOUNDRY_CORE_VERSION
    stats["systemId"] = "dnd5e"
    stats["systemVersion"] = DND5E_SYSTEM_VERSION
    result["_stats"] = stats

    _validate_advancement(
        advancement,
        report,
        allow_blank_scale_identifier=True,
    )
    report.class_name = name
    report.identifier = identifier
    report.input_format = "foundry"
    return result


def build_class(
    data: dict[str, Any],
    *,
    source: str = "",
) -> tuple[dict[str, Any], BuildReport]:
    """Создать или нормализовать Item класса и вернуть отчёт."""
    if not isinstance(data, dict):
        raise ClassBuilderError("Корень входного JSON должен быть объектом.")
    report = BuildReport(source=source)
    is_native = data.get("type") == "class" and isinstance(data.get("system"), dict)
    result = _normalize_native(data, report) if is_native else _build_compact(data, report)
    return result, report


def _atomic_json_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _default_output(source: Path) -> Path:
    return source.with_name(f"{source.stem}_foundry.json")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Создание и проверка Item класса Foundry D&D5e."
    )
    parser.add_argument("input", type=Path, help="Компактный JSON или экспорт class.")
    parser.add_argument("-o", "--output", type=Path, help="Путь готового JSON.")
    parser.add_argument("--report", type=Path, help="Путь технического отчёта.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Только проверить JSON; готовый файл не записывается.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    source = args.input.resolve()
    try:
        with source.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        result, report = build_class(data, source=str(source))
        output = (args.output or _default_output(source)).resolve()
        report.output = "" if args.check else str(output)
        if not args.check:
            _atomic_json_write(output, result)
        if args.report:
            _atomic_json_write(args.report.resolve(), asdict(report))
        print(
            f"OK: {report.class_name} | {report.input_format} | "
            f"{len(result['system']['advancement'])} advancement"
        )
        if report.warnings:
            for warning in report.warnings:
                print(f"WARNING: {warning}", file=sys.stderr)
        if not args.check:
            print(output)
        return 0
    except (OSError, json.JSONDecodeError, ClassBuilderError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
