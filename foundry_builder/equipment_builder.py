#!/usr/bin/env python3
"""Сборка экипировки Foundry VTT 13.351 / D&D5e 5.3.3.

Поддерживаются:
  * отдельный предмет ``type="equipment"``;
  * упрощённый JSON экипировки;
  * полный JSON актёра с вложенными предметами экипировки;
  * броня, щиты, магические бонусы, свойства и настройка;
  * заряды и восстановление;
  * activities attack/save/damage/heal/utility/cast;
  * Active Effects и настройки Midi-QOL/DAE.

Целевые версии:
    Foundry VTT 13.351
    D&D5e 5.3.3
    Midi-QOL 13.0.64
    DAE 13.0.29
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import feat_builder
import enhancement_policy
import midi_compat
import project_config


ROOT = Path(__file__).resolve().parent
TEMPLATES_PATH = ROOT / "templates.json"

WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}

ACTIVITY_TYPES = {"attack", "save", "damage", "heal", "utility", "cast"}
ARMOR_TYPES = {"light", "medium", "heavy", "shield"}

TYPE_ALIASES = {
    "light": "light",
    "лёгкий": "light",
    "легкий": "light",
    "лёгкая": "light",
    "легкая": "light",
    "medium": "medium",
    "средний": "medium",
    "средняя": "medium",
    "heavy": "heavy",
    "тяжёлый": "heavy",
    "тяжелый": "heavy",
    "тяжёлая": "heavy",
    "тяжелая": "heavy",
    "shield": "shield",
    "щит": "shield",
    "clothing": "clothing",
    "одежда": "clothing",
    "ring": "ring",
    "кольцо": "ring",
    "trinket": "trinket",
    "безделушка": "trinket",
    "wand": "wand",
    "жезл": "wand",
    "rod": "rod",
    "скипетр": "rod",
    "staff": "staff",
    "посох": "staff",
    "wondrous": "trinket",
    "чудесный предмет": "trinket",
}

RARITY_ALIASES = {
    "": "",
    "common": "common",
    "обычный": "common",
    "uncommon": "uncommon",
    "необычный": "uncommon",
    "rare": "rare",
    "редкий": "rare",
    "veryrare": "veryRare",
    "very rare": "veryRare",
    "очень редкий": "veryRare",
    "legendary": "legendary",
    "легендарный": "legendary",
    "artifact": "artifact",
    "артефакт": "artifact",
}

PROPERTY_ALIASES = {
    "magic": "mgc",
    "magical": "mgc",
    "магический": "mgc",
    "mgc": "mgc",
    "gear": "gear",
    "экипировка": "gear",
    "stealthdisadvantage": "stealthDisadvantage",
    "stealth_disadvantage": "stealthDisadvantage",
    "помеха скрытности": "stealthDisadvantage",
    "focus": "foc",
    "spellcasting focus": "foc",
    "фокусировка": "foc",
    "foc": "foc",
}

ATTUNEMENT_REQUIRED = re.compile(
    r"(?:requires?\s+attunement|attunement\s+required|"
    r"требует(?:ся)?\s+настройк|необходим\w*\s+настройк|"
    r"нужна\s+настройк)",
    re.IGNORECASE,
)
ATTUNEMENT_NOT_REQUIRED = re.compile(
    r"(?:does\s+not\s+require\s+attunement|without\s+attunement|"
    r"не\s+требует(?:ся)?\s+настройк|без\s+настройк)",
    re.IGNORECASE,
)


class EquipmentBuilderError(Exception):
    """Ошибка, из-за которой безопасная обработка невозможна."""


@dataclass
class Change:
    path: str
    action: str
    old: Any = None
    new: Any = None


@dataclass
class EquipmentResult:
    name: str
    status: str
    equipment_type: str
    activities_before: int
    activities_after: int
    effects_after: int
    message: str


@dataclass
class BuildReport:
    source: str
    output: str = ""
    changes: list[Change] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    equipment: list[EquipmentResult] = field(default_factory=list)

    def change(self, path: str, action: str, old: Any, new: Any) -> None:
        self.changes.append(Change(path, action, old, new))

    def warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number(value: Any, default: int | float = 0) -> int | float:
    if _is_number(value):
        return value
    if isinstance(value, str):
        text = value.strip().replace(",", ".").removeprefix("+")
        try:
            result = float(text)
            return int(result) if result.is_integer() else result
        except ValueError:
            return default
    return default


def _integer(value: Any, default: int = 0) -> int:
    return int(_number(value, default))


def _plain_text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    if not isinstance(value, str):
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _slug(value: str) -> str:
    text = value.casefold().replace("ё", "е")
    transliteration = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
        "е": "e", "ж": "zh", "з": "z", "и": "i", "й": "i",
        "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
        "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh",
        "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e",
        "ю": "yu", "я": "ya",
    }
    text = "".join(transliteration.get(character, character) for character in text)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "ekipirovka"


def _safe_filename(value: str) -> str:
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    filename = re.sub(r"\s+", " ", filename)
    if not filename:
        filename = "Безымянная экипировка"
    if filename.upper() in WINDOWS_RESERVED_FILENAMES:
        filename = f"_{filename}"
    return filename


def _ensure_dict(
    parent: dict[str, Any],
    key: str,
    report: BuildReport,
    path: str,
) -> dict[str, Any]:
    old = parent.get(key)
    if isinstance(old, dict):
        return old
    parent[key] = {}
    report.change(f"{path}.{key}", "created_object", old, {})
    return parent[key]


def _ensure_list(
    parent: dict[str, Any],
    key: str,
    report: BuildReport,
    path: str,
) -> list[Any]:
    old = parent.get(key)
    if isinstance(old, list):
        return old
    parent[key] = []
    report.change(f"{path}.{key}", "created_array", old, [])
    return parent[key]


def _default(
    parent: dict[str, Any],
    key: str,
    value: Any,
    report: BuildReport,
    path: str,
) -> Any:
    if key not in parent or parent[key] is None:
        old = parent.get(key)
        parent[key] = deepcopy(value)
        report.change(f"{path}.{key}", "filled_default", old, parent[key])
    return parent[key]


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = deepcopy(value)


def load_template(template_key: str) -> dict[str, Any]:
    """Загружает именованную секцию из единого реестра шаблонов."""
    try:
        with TEMPLATES_PATH.open("r", encoding="utf-8-sig") as file:
            registry = json.load(file)
    except FileNotFoundError as error:
        raise EquipmentBuilderError(
            f"Не найден реестр шаблонов: {TEMPLATES_PATH}"
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise EquipmentBuilderError(
            f"Не удалось прочитать {TEMPLATES_PATH}: {error}"
        ) from error
    if not isinstance(registry, dict):
        raise EquipmentBuilderError("Корень templates.json должен быть JSON-объектом.")
    templates = registry.get("templates")
    if not isinstance(templates, dict):
        raise EquipmentBuilderError(
            "templates.json не содержит объект «templates»."
        )
    template = templates.get(template_key)
    if not isinstance(template, dict):
        raise EquipmentBuilderError(
            f"Секция шаблона «{template_key}» отсутствует или не является объектом."
        )
    return template


def _load_template() -> dict[str, Any]:
    return load_template("equipment")


def _partial_item(source: dict[str, Any]) -> dict[str, Any]:
    """Разворачивает компактный JSON в полноценный Item."""
    item = deepcopy(_load_template())
    item["name"] = str(source.get("name") or "Безымянная экипировка")
    if source.get("img") not in (None, ""):
        item["img"] = str(source["img"])

    source_system = source.get("system")
    if isinstance(source_system, dict):
        _deep_merge(item["system"], source_system)

    system_fields = (
        "activities",
        "armor",
        "attuned",
        "attunement",
        "container",
        "cover",
        "crew",
        "description",
        "equipped",
        "hp",
        "identified",
        "identifier",
        "price",
        "proficient",
        "properties",
        "quantity",
        "rarity",
        "source",
        "speed",
        "strength",
        "unidentified",
        "uses",
        "weight",
    )
    for key in system_fields:
        if key in source and key != "activities":
            item["system"][key] = deepcopy(source[key])

    equipment_type = source.get("equipment_type")
    raw_type = source.get("type")
    if equipment_type is None and isinstance(raw_type, dict):
        equipment_type = raw_type
    if equipment_type is not None:
        item["system"]["type"] = deepcopy(equipment_type)

    mechanics = source.get("mechanics")
    if isinstance(mechanics, dict):
        item["mechanics"] = deepcopy(mechanics)
    else:
        compact_mechanics: dict[str, Any] = {}
        if isinstance(source.get("activities"), list):
            compact_mechanics["activities"] = deepcopy(source["activities"])
        if isinstance(source.get("effects"), list):
            compact_mechanics["effects"] = deepcopy(source["effects"])
        if compact_mechanics:
            item["mechanics"] = compact_mechanics

    if isinstance(source.get("flags"), dict):
        item["flags"] = deepcopy(source["flags"])
    if "enhancement_policy" in source:
        item["enhancement_policy"] = deepcopy(source["enhancement_policy"])
    else:
        item.pop("enhancement_policy", None)
    item["type"] = "equipment"
    return item


def _canonical_type(value: Any) -> str:
    text = str(value or "").casefold().replace("ё", "е").strip()
    return TYPE_ALIASES.get(text, text)


def _canonical_rarity(value: Any) -> str:
    text = str(value or "").casefold().replace("ё", "е").strip()
    compact = re.sub(r"[\s_-]+", " ", text)
    return RARITY_ALIASES.get(compact, RARITY_ALIASES.get(text, str(value or "")))


def _canonical_properties(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [
            part.strip()
            for part in re.split(r"[,;/]+", value)
            if part.strip()
        ]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []
    result: list[str] = []
    for raw in values:
        text = str(raw or "").casefold().replace("ё", "е").strip()
        canonical = PROPERTY_ALIASES.get(text, str(raw or "").strip())
        if canonical and canonical not in result:
            result.append(canonical)
    return result


def _attunement(value: Any, description: str) -> str:
    if isinstance(value, bool):
        return "required" if value else ""
    text = str(value or "").casefold().replace("ё", "е").strip()
    if text in {"required", "requires", "require", "yes", "true", "да"}:
        return "required"
    if text in {
        "none",
        "not required",
        "not_required",
        "no",
        "false",
        "нет",
        "не требуется",
    }:
        return ""
    if ATTUNEMENT_NOT_REQUIRED.search(description):
        return ""
    if ATTUNEMENT_REQUIRED.search(description):
        return "required"
    return str(value or "")


def _extract_mechanics(item: dict[str, Any]) -> dict[str, Any]:
    system = item.get("system")
    candidates = [
        item.get("mechanics"),
        system.get("mechanics") if isinstance(system, dict) else None,
    ]
    flags = item.get("flags")
    if isinstance(flags, dict):
        namespace = flags.get("foundry-content-generator")
        if isinstance(namespace, dict):
            candidates.append(namespace.get("mechanics"))
    for candidate in candidates:
        if isinstance(candidate, dict):
            return deepcopy(candidate)
    return {}


def _consume_mechanics(
    item: dict[str, Any],
    system: dict[str, Any],
    report: BuildReport,
    path: str,
) -> None:
    for parent, parent_path in ((item, path), (system, f"{path}.system")):
        if "mechanics" in parent:
            old = parent.pop("mechanics")
            report.change(
                f"{parent_path}.mechanics",
                "consumed_builder_metadata",
                old,
                None,
            )
    flags = item.get("flags")
    namespace = (
        flags.get("foundry-content-generator")
        if isinstance(flags, dict)
        else None
    )
    if isinstance(namespace, dict) and "mechanics" in namespace:
        old = namespace.pop("mechanics")
        report.change(
            f"{path}.flags.foundry-content-generator.mechanics",
            "consumed_builder_metadata",
            old,
            None,
        )


def _apply_uses(
    system: dict[str, Any],
    mechanics: dict[str, Any],
    report: BuildReport,
    path: str,
) -> bool:
    value = mechanics.get("uses")
    if not isinstance(value, dict):
        return False
    uses = _ensure_dict(system, "uses", report, path)
    old = deepcopy(uses)
    if "max" in value:
        uses["max"] = str(value.get("max") or "")
    if "spent" in value:
        uses["spent"] = max(0, _integer(value.get("spent"), 0))
    else:
        uses.setdefault("spent", 0)
    if isinstance(value.get("recovery"), list):
        uses["recovery"] = deepcopy(value["recovery"])
    else:
        uses.setdefault("recovery", [])
    if uses != old:
        report.change(f"{path}.uses", "configured_uses", old, deepcopy(uses))
        return True
    return False


def _activity_id(index: int) -> str:
    if index < 0 or index > 999:
        raise EquipmentBuilderError(
            "Поддерживается не более 1000 activities на предмет."
        )
    return f"dnd5eactivity{index:03d}"


def _activity_data(
    parent: dict[str, Any],
    spec: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    result = deepcopy(parent)
    result.pop("activities", None)
    result["_auto_consume_uses"] = index == 0
    for key, value in spec.items():
        if key not in {"type", "_id"}:
            result[key] = deepcopy(value)
    if "consume_uses" in spec:
        result["_auto_consume_uses"] = bool(spec["consume_uses"])
    if "consumption" in spec or "resource" in spec:
        result["_auto_consume_uses"] = False
    return result


def _build_cast_activity(
    mechanics: dict[str, Any],
    activity_id: str,
) -> dict[str, Any] | None:
    spell = mechanics.get("spell")
    if not isinstance(spell, dict):
        return None
    uuid = str(spell.get("uuid") or "").strip()
    if not uuid:
        return None

    activity = feat_builder._base_activity(activity_id, "utility")
    activity["type"] = "cast"
    activity.pop("roll", None)
    feat_builder._apply_activity_common(activity, mechanics)

    challenge = spell.get("challenge")
    if not isinstance(challenge, dict):
        challenge = {}
    save = challenge.get("save", spell.get("save_dc"))
    attack = challenge.get("attack", spell.get("attack_bonus"))
    override = challenge.get("override")
    if override is None:
        override = save not in (None, "") or attack not in (None, "")

    properties = spell.get("properties")
    if not isinstance(properties, list):
        properties = []
    activity["spell"] = {
        "uuid": uuid,
        "challenge": {
            "attack": (
                _number(attack) if attack not in (None, "") else None
            ),
            "save": _integer(save) if save not in (None, "") else None,
            "override": bool(override),
        },
        "level": max(0, _integer(spell.get("level"), 0)),
        "properties": [str(value) for value in properties],
        "ability": str(spell.get("ability") or ""),
        "spellbook": bool(spell.get("spellbook", True)),
    }
    activity["consumption"]["spellSlot"] = bool(
        mechanics.get("spell_slot", True)
    )
    scaling = mechanics.get("scaling")
    if isinstance(scaling, dict):
        activity["consumption"]["scaling"].update(deepcopy(scaling))
    midi_compat.normalize_activity(activity)
    return activity


def _build_one_activity(
    activity_type: str,
    data: dict[str, Any],
    activity_id: str,
) -> dict[str, Any] | None:
    if activity_type == "attack":
        return feat_builder._build_attack_activity(data, activity_id)
    if activity_type == "save":
        return feat_builder._build_save_activity(data, activity_id)
    if activity_type == "damage":
        return feat_builder._build_damage_activity(data, activity_id)
    if activity_type == "heal":
        return feat_builder._build_heal_activity(data, activity_id)
    if activity_type == "utility":
        return feat_builder._build_utility_activity(data, activity_id)
    if activity_type == "cast":
        return _build_cast_activity(data, activity_id)
    return None


def _inferred_activity_type(mechanics: dict[str, Any]) -> str:
    explicit = str(mechanics.get("activity_type") or "").casefold().strip()
    if explicit:
        return explicit
    if isinstance(mechanics.get("spell"), dict):
        return "cast"
    if isinstance(mechanics.get("attack"), dict):
        return "attack"
    if isinstance(mechanics.get("save"), dict):
        return "save"
    if isinstance(mechanics.get("healing"), dict):
        return "heal"
    if isinstance(mechanics.get("damage"), list) and mechanics["damage"]:
        return "damage"
    if (
        isinstance(mechanics.get("activation"), dict)
        or isinstance(mechanics.get("consumption"), list)
        or isinstance(mechanics.get("resource"), dict)
    ):
        return "utility"
    return ""


def _build_activities(
    mechanics: dict[str, Any],
    item_name: str,
    report: BuildReport,
) -> list[dict[str, Any]]:
    if mechanics.get("passive"):
        return []
    specs = mechanics.get("activities")
    if not isinstance(specs, list) or not specs:
        activity_type = _inferred_activity_type(mechanics)
        if not activity_type:
            return []
        specs = [{"type": activity_type}]

    result: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict):
            report.warning(
                f"{item_name}: activity #{index + 1} пропущена — "
                "ожидался JSON-объект."
            )
            continue
        activity_type = str(spec.get("type") or "").casefold().strip()
        if activity_type not in ACTIVITY_TYPES:
            report.warning(
                f"{item_name}: неизвестный тип activity "
                f"«{activity_type or 'пусто'}»; элемент #{index + 1} пропущен."
            )
            continue
        raw_id = str(spec.get("_id") or "").strip()
        if raw_id and not re.fullmatch(r"[A-Za-z0-9]{16}", raw_id):
            report.warning(
                f"{item_name}: некорректный _id activity "
                f"«{raw_id}» заменён автоматически."
            )
            raw_id = ""
        activity_id = raw_id or _activity_id(index)
        replacement = index
        while activity_id in used_ids:
            report.warning(
                f"{item_name}: повторяющийся _id activity "
                f"«{activity_id}» заменён автоматически."
            )
            replacement += 1
            activity_id = _activity_id(replacement)
        used_ids.add(activity_id)

        data = _activity_data(mechanics, spec, index)
        activity = _build_one_activity(activity_type, data, activity_id)
        if activity is None:
            report.warning(
                f"{item_name}: activity "
                f"«{spec.get('activity_name') or activity_type}» не создана — "
                "отсутствуют обязательные механические поля."
            )
            continue
        uses_data = data.get("uses")
        if (
            bool(data.get("_auto_consume_uses"))
            and isinstance(uses_data, dict)
            and str(uses_data.get("max") or "").strip()
            and not activity["consumption"].get("targets")
        ):
            activity["consumption"]["targets"] = [
                {
                    "type": "itemUses",
                    "target": "",
                    "value": "1",
                    "scaling": {"mode": "", "formula": ""},
                }
            ]
        result.append(activity)
    return result


def _audit_existing_activities(
    activities: dict[str, Any],
    item_name: str,
    report: BuildReport,
    path: str,
) -> None:
    for key, activity in activities.items():
        if not isinstance(activity, dict):
            report.warning(
                f"{item_name}: существующая activity «{key}» не является объектом."
            )
            continue
        for relative_path in midi_compat.normalize_activity(activity):
            report.change(
                f"{path}.{key}.{relative_path}",
                "added_midi_qol_default",
                None,
                deepcopy(activity),
            )
        activity_type = str(activity.get("type") or "").casefold()
        if activity_type not in ACTIVITY_TYPES:
            report.warning(
                f"{item_name}: существующая activity «{key}» имеет "
                f"неизвестный тип «{activity_type or 'пусто'}»."
            )
        raw_id = str(activity.get("_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9]{16}", raw_id):
            report.warning(
                f"{item_name}: существующая activity «{key}» имеет "
                f"некорректный _id «{raw_id or 'пусто'}»."
            )
        elif raw_id != str(key):
            report.warning(
                f"{item_name}: ключ activity «{key}» не совпадает "
                f"с её _id «{raw_id}»."
            )


def _normalize_item(
    item: dict[str, Any],
    report: BuildReport,
    path: str,
) -> None:
    name = str(item.get("name") or "").strip()
    if not name:
        old = item.get("name")
        name = "Безымянная экипировка"
        item["name"] = name
        report.change(f"{path}.name", "filled_required_name", old, name)
    else:
        item["name"] = name

    old_type = item.get("type")
    if old_type != "equipment":
        item["type"] = "equipment"
        report.change(
            f"{path}.type", "normalized_item_type", old_type, "equipment"
        )
    _default(
        item,
        "img",
        "systems/dnd5e/icons/svg/items/equipment.svg",
        report,
        path,
    )
    _default(item, "folder", None, report, path)
    _default(item, "flags", {}, report, path)
    _default(
        item,
        "_stats",
        {
            "coreVersion": project_config.EXPORT_CORE_VERSION,
            "systemId": "dnd5e",
            "systemVersion": project_config.DND5E_VERSION,
            "createdTime": 0,
            "modifiedTime": 0,
            "lastModifiedBy": None,
            "exportSource": None,
        },
        report,
        path,
    )

    system = _ensure_dict(item, "system", report, path)
    effects = _ensure_list(item, "effects", report, path)

    description = system.get("description")
    if isinstance(description, str):
        system["description"] = {"value": description, "chat": ""}
        report.change(
            f"{path}.system.description",
            "expanded_description",
            description,
            deepcopy(system["description"]),
        )
    description_data = _ensure_dict(
        system, "description", report, f"{path}.system"
    )
    _default(description_data, "value", "", report, f"{path}.system.description")
    _default(description_data, "chat", "", report, f"{path}.system.description")
    description_text = _plain_text(description_data)

    source = _ensure_dict(system, "source", report, f"{path}.system")
    _default(source, "custom", "", report, f"{path}.system.source")
    _default(source, "book", "", report, f"{path}.system.source")
    _default(source, "page", "", report, f"{path}.system.source")
    _default(source, "license", "", report, f"{path}.system.source")
    _default(source, "rules", "2024", report, f"{path}.system.source")
    _default(source, "revision", 1, report, f"{path}.system.source")

    _default(system, "identifier", _slug(name), report, f"{path}.system")
    _default(system, "identified", True, report, f"{path}.system")
    _default(system, "quantity", 1, report, f"{path}.system")
    _default(system, "equipped", False, report, f"{path}.system")
    _default(system, "attuned", False, report, f"{path}.system")
    _default(system, "proficient", None, report, f"{path}.system")
    _default(system, "strength", None, report, f"{path}.system")
    _default(system, "cover", None, report, f"{path}.system")
    _default(system, "container", None, report, f"{path}.system")

    for field_name, default_value in (
        ("unidentified", {"description": ""}),
        ("weight", {"value": 0, "units": "lb"}),
        ("price", {"value": 0, "denomination": "gp"}),
        ("crew", {"value": []}),
    ):
        field_data = _ensure_dict(system, field_name, report, f"{path}.system")
        for key, value in default_value.items():
            _default(
                field_data,
                key,
                value,
                report,
                f"{path}.system.{field_name}",
            )

    type_data = system.get("type")
    if isinstance(type_data, str):
        old = type_data
        type_data = {"value": old, "baseItem": ""}
        system["type"] = type_data
        report.change(
            f"{path}.system.type",
            "expanded_equipment_type",
            old,
            deepcopy(type_data),
        )
    type_data = _ensure_dict(system, "type", report, f"{path}.system")
    raw_equipment_type = type_data.get("value")
    equipment_type = _canonical_type(raw_equipment_type)
    if equipment_type != raw_equipment_type:
        type_data["value"] = equipment_type
        report.change(
            f"{path}.system.type.value",
            "normalized_equipment_type",
            raw_equipment_type,
            equipment_type,
        )
    _default(type_data, "value", "", report, f"{path}.system.type")
    _default(type_data, "baseItem", "", report, f"{path}.system.type")

    armor = system.get("armor")
    if _is_number(armor) or isinstance(armor, str):
        old = armor
        armor = {"value": _number(armor), "dex": None}
        system["armor"] = armor
        report.change(
            f"{path}.system.armor",
            "expanded_armor",
            old,
            deepcopy(armor),
        )
    armor = _ensure_dict(system, "armor", report, f"{path}.system")
    _default(armor, "value", None, report, f"{path}.system.armor")
    _default(armor, "dex", None, report, f"{path}.system.armor")
    if "magicalBonus" in armor and armor["magicalBonus"] not in (None, ""):
        old_bonus = armor["magicalBonus"]
        armor["magicalBonus"] = str(_integer(old_bonus))
        if armor["magicalBonus"] != old_bonus:
            report.change(
                f"{path}.system.armor.magicalBonus",
                "normalized_magical_bonus",
                old_bonus,
                armor["magicalBonus"],
            )
    elif equipment_type in ARMOR_TYPES:
        match = re.search(r"(?:^|\s)\+([1-3])(?:\s|$)", name)
        if match:
            armor["magicalBonus"] = match.group(1)
            report.change(
                f"{path}.system.armor.magicalBonus",
                "inferred_magical_bonus",
                None,
                armor["magicalBonus"],
            )

    old_rarity = system.get("rarity")
    rarity = _canonical_rarity(old_rarity)
    if rarity != old_rarity:
        system["rarity"] = rarity
        report.change(
            f"{path}.system.rarity",
            "normalized_rarity",
            old_rarity,
            rarity,
        )
    _default(system, "rarity", "", report, f"{path}.system")

    old_attunement = system.get("attunement")
    attunement = _attunement(old_attunement, description_text)
    if attunement != old_attunement:
        system["attunement"] = attunement
        report.change(
            f"{path}.system.attunement",
            (
                "inferred_attunement"
                if old_attunement in (None, "")
                else "normalized_attunement"
            ),
            old_attunement,
            attunement,
        )
    _default(system, "attunement", "", report, f"{path}.system")
    if system.get("attunement") != "required" and system.get("attuned"):
        old = system["attuned"]
        system["attuned"] = False
        report.change(
            f"{path}.system.attuned",
            "cleared_impossible_attuned_state",
            old,
            False,
        )

    properties = _canonical_properties(system.get("properties"))
    if "gear" not in properties:
        properties.append("gear")
    magical_bonus = _integer(armor.get("magicalBonus"), 0)
    if (system.get("rarity") or magical_bonus) and "mgc" not in properties:
        properties.append("mgc")
    if properties != system.get("properties"):
        old = system.get("properties")
        system["properties"] = properties
        report.change(
            f"{path}.system.properties",
            "normalized_properties",
            old,
            deepcopy(properties),
        )

    try:
        enhancement_policy.apply_item_policy(item, report, path)
    except enhancement_policy.EnhancementPolicyError as error:
        raise EquipmentBuilderError(str(error)) from error

    uses = _ensure_dict(system, "uses", report, f"{path}.system")
    _default(uses, "max", "", report, f"{path}.system.uses")
    _default(uses, "spent", 0, report, f"{path}.system.uses")
    _ensure_list(uses, "recovery", report, f"{path}.system.uses")

    activities = system.get("activities")
    if isinstance(activities, list):
        old = deepcopy(activities)
        converted: dict[str, Any] = {}
        for index, activity in enumerate(activities):
            if not isinstance(activity, dict):
                continue
            activity_id = str(activity.get("_id") or _activity_id(index))
            activity["_id"] = activity_id
            converted[activity_id] = activity
        system["activities"] = converted
        activities = converted
        report.change(
            f"{path}.system.activities",
            "converted_activity_array",
            old,
            deepcopy(converted),
        )
    elif not isinstance(activities, dict):
        old = activities
        activities = {}
        system["activities"] = activities
        report.change(
            f"{path}.system.activities",
            "created_object",
            old,
            {},
        )

    before = len(activities)
    if before:
        _audit_existing_activities(
            activities,
            name,
            report,
            f"{path}.system.activities",
        )
        report.equipment.append(
            EquipmentResult(
                name,
                "preserved",
                equipment_type,
                before,
                before,
                len(effects),
                "Существующие activities сохранены без замены.",
            )
        )
        return

    mechanics = _extract_mechanics(item)
    if (
        not isinstance(mechanics.get("uses"), dict)
        and str(uses.get("max") or "").strip()
    ):
        mechanics["uses"] = deepcopy(uses)
    _apply_uses(system, mechanics, report, f"{path}.system")
    _consume_mechanics(item, system, report, path)
    built_activities = _build_activities(mechanics, name, report)
    built_effects = feat_builder._build_effects(
        mechanics,
        built_activities,
        name,
        report,
        effects,
    )

    for effect in built_effects:
        effects.append(effect)
        report.change(
            f"{path}.effects[{len(effects) - 1}]",
            "created_active_effect",
            None,
            deepcopy(effect),
        )
    for activity in built_activities:
        activities[activity["_id"]] = activity
        report.change(
            f"{path}.system.activities.{activity['_id']}",
            f"created_{activity['type']}_activity",
            None,
            deepcopy(activity),
        )

    if built_activities:
        status = "created_activities"
        message = "Созданы activities: " + ", ".join(
            activity["type"] for activity in built_activities
        ) + "."
    elif built_effects:
        status = "created_effects"
        message = "Созданы постоянные Active Effects."
    else:
        status = "passive_or_manual"
        message = "Предмет сохранён без нажимаемой активности."
    if built_effects:
        message += f" Active Effects: {len(built_effects)}."

    report.equipment.append(
        EquipmentResult(
            name,
            status,
            equipment_type,
            before,
            len(activities),
            len(effects),
            message,
        )
    )


def normalize_document(
    source: dict[str, Any],
    source_name: str = "",
) -> tuple[dict[str, Any], BuildReport, str]:
    """Нормализует актёра, Item equipment или компактный JSON предмета."""
    if not isinstance(source, dict):
        raise EquipmentBuilderError("Корень JSON должен быть объектом.")

    document_type = source.get("type")
    is_actor = document_type == "npc" or (
        isinstance(source.get("items"), list)
        and isinstance(source.get("system"), dict)
        and document_type not in {"equipment"}
    )
    report = BuildReport(source=source_name)

    if is_actor:
        document = deepcopy(source)
        items = document.get("items")
        if not isinstance(items, list):
            raise EquipmentBuilderError("У актёра items должен быть массивом.")
        for index, item in enumerate(items):
            if isinstance(item, dict) and item.get("type") == "equipment":
                if not isinstance(item.get("system"), dict):
                    item = _partial_item(item)
                    items[index] = item
                _normalize_item(item, report, f"$.items[{index}]")
        return document, report, "actor"

    if document_type == "equipment" and isinstance(source.get("system"), dict):
        document = deepcopy(source)
    else:
        document = _partial_item(source)
    _normalize_item(document, report, "$")
    return document, report, "equipment"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except FileNotFoundError as error:
        raise EquipmentBuilderError(f"Файл не найден: {path}") from error
    except json.JSONDecodeError as error:
        raise EquipmentBuilderError(
            f"Ошибка JSON в {path}, строка {error.lineno}, "
            f"столбец {error.colno}: {error.msg}"
        ) from error
    except OSError as error:
        raise EquipmentBuilderError(f"Не удалось прочитать {path}: {error}") from error
    if not isinstance(data, dict):
        raise EquipmentBuilderError("Корень JSON должен быть объектом.")
    return data


def _atomic_json_write(path: Path, data: Any, indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(data, temporary, ensure_ascii=False, indent=indent)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except OSError as error:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise EquipmentBuilderError(f"Не удалось записать {path}: {error}") from error


def _default_input() -> Path:
    for candidate in (Path("input/equipment.json"), Path("equipment.json")):
        if candidate.is_file():
            return candidate
    return Path("input/equipment.json")


def _default_output(document: dict[str, Any], kind: str) -> Path:
    name = _safe_filename(str(document.get("name") or "Экипировка"))
    if kind == "actor":
        return Path("output/actors") / f"{name}_foundry.json"
    return Path("output/equipment") / f"{name}_foundry.json"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Собирает экипировку для Foundry VTT 13.351 / D&D5e 5.3.3 "
            "с поддержкой Midi-QOL/DAE."
        )
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=None,
        help="Исходный JSON предмета или актёра.",
    )
    parser.add_argument("-o", "--output", type=Path, help="Итоговый JSON.")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("logs/equipment_builder_report.json"),
        help="JSON-отчёт.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        choices=range(1, 9),
        metavar="1-8",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    source_path = args.source or _default_input()
    try:
        source = _load_json(source_path)
        document, report, kind = normalize_document(
            source,
            source_name=str(source_path),
        )
        compatibility = midi_compat.audit_document(document)
        if compatibility["errors"]:
            details = "; ".join(compatibility["errors"][:5])
            raise EquipmentBuilderError(
                "JSON не прошёл проверку Midi-QOL/DAE: " + details
            )
        output_path = args.output or _default_output(document, kind)
        report.output = str(output_path)
        _atomic_json_write(output_path, document, args.indent)
        _atomic_json_write(args.report, asdict(report), args.indent)
    except EquipmentBuilderError as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return 1

    print(f"Готово: {document.get('name', 'Экипировка')}")
    print(f"JSON: {output_path}")
    print(f"Отчёт: {args.report}")
    if report.equipment:
        counts: dict[str, int] = {}
        for result in report.equipment:
            counts[result.status] = counts.get(result.status, 0) + 1
        print(
            "Экипировка: "
            + ", ".join(
                f"{status}: {count}"
                for status, count in sorted(counts.items())
            )
        )
    if report.warnings:
        print(f"Предупреждений: {len(report.warnings)}")
    print(
        "Midi-QOL/DAE: "
        f"{compatibility['activities']} activities, "
        f"{compatibility['effects']} Active Effects, структурных ошибок нет"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
