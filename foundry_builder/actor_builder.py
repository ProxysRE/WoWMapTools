#!/usr/bin/env python3
"""
Нормализация JSON актёра Foundry VTT.

Билдер ориентирован на NPC для Foundry VTT 13.351 / D&D5e 5.3.3.
Билдер сохраняет неизвестные и уже корректные поля, исправляет только
структуру самого актёра и составляет отчёт по вложенным предметам.

Запуск:
    python actor_builder.py input/npc.json
    python actor_builder.py input/npc.json -o output/actors/npc.json

Если путь не указан, программа ищет input/npc.json, затем npc.json.
Без параметра -o имя результата берётся из поля name самого НПС.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import project_config


ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")
SPELL_SLOT_KEYS = tuple(f"spell{level}" for level in range(10)) + ("pact",)
ABILITY_ALIASES = {
    "strength": "str",
    "dexterity": "dex",
    "constitution": "con",
    "intelligence": "int",
    "wisdom": "wis",
    "charisma": "cha",
}
MOVEMENT_KEYS = ("walk", "fly", "swim", "climb", "burrow")
SENSE_KEYS = ("darkvision", "blindsight", "tremorsense", "truesight")
TRAIT_KEYS = ("di", "dr", "dv", "ci", "languages")
VALID_AC_CALCULATIONS = {
    "default",
    "flat",
    "natural",
    "formula",
    "mage",
    "draconic",
    "unarmoredMonk",
    "unarmoredBarb",
}
FOUNDRY_CORE_VERSION = project_config.EXPORT_CORE_VERSION
DND5E_SYSTEM_VERSION = project_config.DND5E_VERSION
WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}

CR_XP = {
    0: 10,
    0.125: 25,
    0.25: 50,
    0.5: 100,
    1: 200,
    2: 450,
    3: 700,
    4: 1100,
    5: 1800,
    6: 2300,
    7: 2900,
    8: 3900,
    9: 5000,
    10: 5900,
    11: 7200,
    12: 8400,
    13: 10000,
    14: 11500,
    15: 13000,
    16: 15000,
    17: 18000,
    18: 20000,
    19: 22000,
    20: 25000,
    21: 33000,
    22: 41000,
    23: 50000,
    24: 62000,
    25: 75000,
    26: 90000,
    27: 105000,
    28: 120000,
    29: 135000,
    30: 155000,
}


class ActorBuilderError(Exception):
    """Ошибка, из-за которой безопасная обработка невозможна."""


@dataclass
class Change:
    path: str
    action: str
    old: Any = None
    new: Any = None


@dataclass
class ItemAudit:
    name: str
    type: str
    status: str
    message: str


@dataclass
class BuildReport:
    source: str
    output: str = ""
    actor_name: str = ""
    changes: list[Change] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    item_audit: list[ItemAudit] = field(default_factory=list)

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
        text = value.strip().replace(",", ".")
        try:
            result = float(text)
            return int(result) if result.is_integer() else result
        except ValueError:
            return default
    return default


def _integer(value: Any, default: int = 0) -> int:
    return int(_number(value, default))


def _dict(
    parent: dict[str, Any],
    key: str,
    report: BuildReport,
    path: str,
) -> dict[str, Any]:
    value = parent.get(key)
    if isinstance(value, dict):
        return value
    replacement: dict[str, Any] = {}
    parent[key] = replacement
    report.change(f"{path}.{key}", "created_object", value, replacement)
    return replacement


def _list(
    parent: dict[str, Any],
    key: str,
    report: BuildReport,
    path: str,
) -> list[Any]:
    value = parent.get(key)
    if isinstance(value, list):
        return value
    replacement: list[Any] = []
    parent[key] = replacement
    report.change(f"{path}.{key}", "created_array", value, replacement)
    return replacement


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


def _convert_number(
    parent: dict[str, Any],
    key: str,
    default: int | float,
    report: BuildReport,
    path: str,
) -> int | float:
    old = parent.get(key)
    new = _number(old, default)
    if old != new or isinstance(old, bool):
        parent[key] = new
        report.change(f"{path}.{key}", "normalized_number", old, new)
    return new


def _convert_nullable_number(
    parent: dict[str, Any],
    key: str,
    report: BuildReport,
    path: str,
) -> int | float | None:
    """Нормализует число, сохраняя пустое значение как null."""
    old = parent.get(key)
    if old is None or (isinstance(old, str) and not old.strip()):
        new = None
    elif _is_number(old):
        new = old
    elif isinstance(old, str):
        text = old.strip().replace(",", ".")
        try:
            parsed = float(text)
            new = int(parsed) if parsed.is_integer() else parsed
        except ValueError:
            new = None
            report.warning(
                f"Некорректная числовая дистанция в {path}.{key}: "
                f"{old!r}. Значение заменено на null."
            )
    else:
        new = None
        report.warning(
            f"Некорректная числовая дистанция в {path}.{key}: "
            f"{old!r}. Значение заменено на null."
        )

    if key not in parent or old != new or isinstance(old, bool):
        parent[key] = new
        report.change(f"{path}.{key}", "normalized_nullable_number", old, new)
    return new


def _normalize_abilities(system: dict[str, Any], report: BuildReport) -> None:
    abilities = _dict(system, "abilities", report, "system")

    for alias, canonical in ABILITY_ALIASES.items():
        if alias in abilities and canonical not in abilities:
            abilities[canonical] = abilities.pop(alias)
            report.change(
                f"system.abilities.{canonical}",
                f"renamed_from_{alias}",
                alias,
                canonical,
            )

    for key in ABILITY_KEYS:
        path = f"system.abilities.{key}"
        ability = abilities.get(key)
        if _is_number(ability) or isinstance(ability, str):
            abilities[key] = {"value": _integer(ability, 10)}
            report.change(path, "expanded_ability", ability, abilities[key])
        ability = _dict(abilities, key, report, "system.abilities")
        _convert_number(ability, "value", 10, report, path)
        _convert_number(ability, "proficient", 0, report, path)
        bonuses = _dict(ability, "bonuses", report, path)
        for bonus in ("check", "save", "skill"):
            _default(bonuses, bonus, "", report, f"{path}.bonuses")


def _normalize_ac(attributes: dict[str, Any], report: BuildReport) -> None:
    old_ac = attributes.get("ac")
    if _is_number(old_ac) or isinstance(old_ac, str):
        value = _number(old_ac, 10)
        attributes["ac"] = {"calc": "flat", "flat": value, "formula": ""}
        report.change(
            "system.attributes.ac",
            "expanded_flat_ac",
            old_ac,
            attributes["ac"],
        )

    ac = _dict(attributes, "ac", report, "system.attributes")
    if "value" in ac and "flat" not in ac:
        old = ac.get("value")
        ac["flat"] = _number(old, 10)
        report.change("system.attributes.ac.flat", "copied_legacy_value", old, ac["flat"])

    calc = _default(ac, "calc", "default", report, "system.attributes.ac")
    if not isinstance(calc, str):
        old = calc
        ac["calc"] = "default"
        report.change("system.attributes.ac.calc", "normalized_text", old, "default")
    elif calc not in VALID_AC_CALCULATIONS:
        report.warning(
            f"Неизвестный способ расчёта КД: {calc!r}. Значение сохранено без изменений."
        )

    calc = ac.get("calc")
    if calc in {"flat", "natural"}:
        _convert_number(ac, "flat", 10, report, "system.attributes.ac")
    else:
        old_flat = ac.get("flat")
        if "flat" not in ac or old_flat is not None:
            ac["flat"] = None
            report.change(
                "system.attributes.ac.flat",
                "cleared_unused_flat_ac",
                old_flat,
                None,
            )
    _default(ac, "formula", "", report, "system.attributes.ac")


def _normalize_hp(attributes: dict[str, Any], report: BuildReport) -> None:
    old_hp = attributes.get("hp")
    if _is_number(old_hp) or isinstance(old_hp, str):
        value = _integer(old_hp, 1)
        attributes["hp"] = {
            "value": value,
            "max": value,
            "temp": 0,
            "tempmax": 0,
            "formula": "",
        }
        report.change(
            "system.attributes.hp",
            "expanded_hp",
            old_hp,
            attributes["hp"],
        )

    hp = _dict(attributes, "hp", report, "system.attributes")
    value = _convert_number(hp, "value", 1, report, "system.attributes.hp")
    if "max" not in hp or hp["max"] is None:
        hp["max"] = value
        report.change("system.attributes.hp.max", "copied_current_hp", None, value)
    else:
        _convert_number(hp, "max", value, report, "system.attributes.hp")
    _convert_number(hp, "temp", 0, report, "system.attributes.hp")
    _convert_number(hp, "tempmax", 0, report, "system.attributes.hp")
    _default(hp, "formula", "", report, "system.attributes.hp")


def _normalize_movement(attributes: dict[str, Any], report: BuildReport) -> None:
    old = attributes.get("movement")
    if _is_number(old) or isinstance(old, str):
        attributes["movement"] = {"walk": _number(old, 30)}
        report.change(
            "system.attributes.movement",
            "expanded_movement",
            old,
            attributes["movement"],
        )
    movement = _dict(attributes, "movement", report, "system.attributes")
    for key in MOVEMENT_KEYS:
        _convert_number(movement, key, 0, report, "system.attributes.movement")
    _default(movement, "units", "ft", report, "system.attributes.movement")
    _default(movement, "hover", False, report, "system.attributes.movement")


def _normalize_senses(attributes: dict[str, Any], report: BuildReport) -> None:
    senses = _dict(attributes, "senses", report, "system.attributes")
    ranges = _dict(senses, "ranges", report, "system.attributes.senses")

    for key in SENSE_KEYS:
        if key in senses:
            old = senses.pop(key)
            current = ranges.get(key)
            if key not in ranges or current is None:
                ranges[key] = old
                report.change(
                    f"system.attributes.senses.ranges.{key}",
                    "moved_legacy_sense",
                    current,
                    old,
                )
            else:
                report.change(
                    f"system.attributes.senses.{key}",
                    "removed_legacy_duplicate",
                    old,
                    None,
                )
        _convert_nullable_number(
            ranges,
            key,
            report,
            "system.attributes.senses.ranges",
        )

    has_range = any(ranges.get(key) not in (None, 0) for key in SENSE_KEYS)
    if "units" not in senses:
        senses["units"] = "ft" if has_range else None
        report.change(
            "system.attributes.senses.units",
            "filled_default",
            None,
            senses["units"],
        )
    _default(senses, "special", "", report, "system.attributes.senses")


def _normalize_attributes(system: dict[str, Any], report: BuildReport) -> None:
    attributes = _dict(system, "attributes", report, "system")
    _normalize_ac(attributes, report)
    _normalize_hp(attributes, report)
    _normalize_movement(attributes, report)
    _normalize_senses(attributes, report)

    init = _dict(attributes, "init", report, "system.attributes")
    _default(init, "ability", "dex", report, "system.attributes.init")
    _default(init, "bonus", "", report, "system.attributes.init")
    raw_spellcasting = _default(
        attributes, "spellcasting", "", report, "system.attributes"
    )
    spellcasting_text = str(raw_spellcasting or "").casefold().strip()
    spellcasting = ABILITY_ALIASES.get(spellcasting_text, spellcasting_text)
    if spellcasting not in {"", *ABILITY_KEYS}:
        report.warning(
            f"Неизвестная характеристика заклинаний: {raw_spellcasting!r}. "
            "Значение очищено."
        )
        spellcasting = ""
    if raw_spellcasting != spellcasting:
        attributes["spellcasting"] = spellcasting
        report.change(
            "system.attributes.spellcasting",
            "normalized_spellcasting_ability",
            raw_spellcasting,
            spellcasting,
        )

    spell = _dict(attributes, "spell", report, "system.attributes")
    old_spell_level = spell.get("level")
    spell_level = max(0, _integer(old_spell_level, 0))
    if "level" not in spell or old_spell_level != spell_level:
        spell["level"] = spell_level
        report.change(
            "system.attributes.spell.level",
            "normalized_spellcaster_level",
            old_spell_level,
            spell_level,
        )
    _convert_number(attributes, "exhaustion", 0, report, "system.attributes")


def _normalize_spell_slots(system: dict[str, Any], report: BuildReport) -> None:
    """Создаёт и нормализует запасы ячеек NPC в формате D&D5e 5.3.3."""
    spells = _dict(system, "spells", report, "system")
    for key in SPELL_SLOT_KEYS:
        path = f"system.spells.{key}"
        slots = _dict(spells, key, report, "system.spells")

        old_value = slots.get("value")
        value = max(0, _integer(old_value, 0))
        if old_value != value or isinstance(old_value, bool):
            slots["value"] = value
            report.change(f"{path}.value", "normalized_spell_slots", old_value, value)

        old_override = slots.get("override")
        if old_override in (None, ""):
            override = None
        else:
            override = max(0, _integer(old_override, 0))
        if "override" not in slots or old_override != override:
            slots["override"] = override
            report.change(
                f"{path}.override",
                "normalized_spell_slot_override",
                old_override,
                override,
            )

    attributes = system.get("attributes")
    if isinstance(attributes, dict):
        spellcasting = str(attributes.get("spellcasting") or "").strip()
        spell = attributes.get("spell")
        spell_level = (
            _integer(spell.get("level"), 0)
            if isinstance(spell, dict)
            else 0
        )
        has_slots = any(
            isinstance(spells.get(key), dict)
            and _integer(spells[key].get("value"), 0) > 0
            for key in SPELL_SLOT_KEYS
        )
        if spellcasting and has_slots and spell_level <= 0:
            report.warning(
                "У NPC заданы характеристика и ячейки заклинаний, но "
                "system.attributes.spell.level равен 0. Foundry покажет "
                "ячейки как временные и не рассчитает собственный максимум."
            )


def _normalize_details(system: dict[str, Any], report: BuildReport) -> None:
    details = _dict(system, "details", report, "system")
    _default(details, "alignment", "", report, "system.details")
    _default(details, "race", "", report, "system.details")

    biography_value = details.get("biography")
    if isinstance(biography_value, str):
        details["biography"] = {"value": biography_value, "public": ""}
        report.change(
            "system.details.biography",
            "expanded_biography",
            biography_value,
            details["biography"],
        )
    biography = _dict(details, "biography", report, "system.details")
    _default(biography, "value", "", report, "system.details.biography")
    _default(biography, "public", "", report, "system.details.biography")

    type_value = details.get("type")
    if isinstance(type_value, str):
        details["type"] = {"value": type_value, "subtype": "", "custom": ""}
        report.change(
            "system.details.type",
            "expanded_creature_type",
            type_value,
            details["type"],
        )
    creature_type = _dict(details, "type", report, "system.details")
    for key in ("value", "subtype", "custom"):
        _default(creature_type, key, "", report, "system.details.type")

    cr = _convert_number(details, "cr", 0, report, "system.details")
    xp = details.get("xp")
    if _is_number(xp) or isinstance(xp, str):
        details["xp"] = {"value": _integer(xp, 0)}
        report.change("system.details.xp", "expanded_xp", xp, details["xp"])
    xp_data = _dict(details, "xp", report, "system.details")
    if "value" not in xp_data or xp_data["value"] is None:
        calculated_xp = CR_XP.get(cr, 0)
        xp_data["value"] = calculated_xp
        report.change(
            "system.details.xp.value",
            "calculated_from_cr",
            None,
            calculated_xp,
        )
    else:
        _convert_number(xp_data, "value", 0, report, "system.details.xp")

    source_value = details.get("source")
    if isinstance(source_value, str):
        details["source"] = {"book": source_value, "page": "", "license": ""}
        report.change(
            "system.details.source",
            "expanded_source",
            source_value,
            details["source"],
        )
    source = _dict(details, "source", report, "system.details")
    for key in ("book", "page", "license"):
        _default(source, key, "", report, "system.details.source")


def _normalize_trait_block(
    traits: dict[str, Any],
    key: str,
    report: BuildReport,
) -> None:
    path = f"system.traits.{key}"
    old = traits.get(key)
    if isinstance(old, list):
        traits[key] = {"value": old, "custom": ""}
        report.change(path, "expanded_trait", old, traits[key])
    elif isinstance(old, str):
        traits[key] = {"value": [], "custom": old}
        report.change(path, "expanded_custom_trait", old, traits[key])

    block = _dict(traits, key, report, "system.traits")
    value = block.get("value")
    if isinstance(value, str):
        normalized = [entry.strip() for entry in value.split(",") if entry.strip()]
        block["value"] = normalized
        report.change(f"{path}.value", "split_text_list", value, normalized)
    else:
        _list(block, "value", report, path)
    _default(block, "custom", "", report, path)


def _normalize_traits(system: dict[str, Any], report: BuildReport) -> None:
    traits = _dict(system, "traits", report, "system")
    _default(traits, "size", "med", report, "system.traits")
    for key in TRAIT_KEYS:
        _normalize_trait_block(traits, key, report)


def _normalize_skills(system: dict[str, Any], report: BuildReport) -> None:
    skills = _dict(system, "skills", report, "system")
    for key, value in list(skills.items()):
        path = f"system.skills.{key}"
        if _is_number(value) or isinstance(value, str):
            skills[key] = {"value": _number(value, 0)}
            report.change(path, "expanded_skill", value, skills[key])
        skill = _dict(skills, key, report, "system.skills")
        _convert_number(skill, "value", 0, report, path)
        _default(skill, "ability", "", report, path)
        bonuses = _dict(skill, "bonuses", report, path)
        _default(bonuses, "check", "", report, f"{path}.bonuses")
        _default(bonuses, "passive", "", report, f"{path}.bonuses")


def _normalize_currency(system: dict[str, Any], report: BuildReport) -> None:
    currency = _dict(system, "currency", report, "system")
    for key in ("pp", "gp", "ep", "sp", "cp"):
        _convert_number(currency, key, 0, report, "system.currency")


def _plain_text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    if not isinstance(value, str):
        return ""
    return re.sub(r"<[^>]+>", " ", value).replace("&nbsp;", " ")


def _infer_resources(
    system: dict[str, Any],
    items: list[Any],
    report: BuildReport,
) -> None:
    legendary_action_found = False
    legendary_resistance_max = 0

    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        lowered = name.casefold()
        if "легендарное действие" in lowered or "legendary action" in lowered:
            legendary_action_found = True
        if (
            "сопротивление легендарного" in lowered
            or "легендарная стойкость" in lowered
            or "легендарная устойчивость" in lowered
            or "legendary resistance" in lowered
        ):
            match = re.search(r"[\(\s](\d+)\s*(?:/|в день|per day)", lowered)
            legendary_resistance_max = int(match.group(1)) if match else 3

    if not legendary_action_found and not legendary_resistance_max:
        return

    resources = _dict(system, "resources", report, "system")

    if legendary_action_found:
        legact = _dict(resources, "legact", report, "system.resources")
        legact_was_missing = (
            legact.get("value") in (None, "")
            or legact.get("max") in (None, "")
        )
        _default(legact, "value", 3, report, "system.resources.legact")
        _default(legact, "max", 3, report, "system.resources.legact")
        if legact_was_missing:
            report.warning(
                "Найдены легендарные действия: создан запас 3/3. "
                "Если у существа другой запас, измените system.resources.legact."
            )

    if legendary_resistance_max:
        legres = _dict(resources, "legres", report, "system.resources")
        legres_was_missing = (
            legres.get("value") in (None, "")
            or legres.get("max") in (None, "")
        )
        _default(
            legres,
            "value",
            legendary_resistance_max,
            report,
            "system.resources.legres",
        )
        if legres_was_missing:
            report.warning(
                "Найдена легендарная стойкость: создан запас "
                f"{legendary_resistance_max}/{legendary_resistance_max}. "
                "Если у существа другой запас, измените "
                "system.resources.legres."
            )
        _default(
            legres,
            "max",
            legendary_resistance_max,
            report,
            "system.resources.legres",
        )


def _activities_count(system: dict[str, Any]) -> int:
    activities = system.get("activities")
    return len(activities) if isinstance(activities, (dict, list)) else 0


def _audit_items(items: list[Any], report: BuildReport) -> None:
    mechanical_words = re.compile(
        r"(спасброс|урон|атак|перезаряд|действи|реакци|бонусн|"
        r"saving throw|damage|attack|recharge|action|reaction)",
        re.IGNORECASE,
    )
    passive_name_patterns = (
        "бестелесное движение",
        "incorporeal movement",
    )

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            report.item_audit.append(
                ItemAudit(
                    name=f"Элемент #{index + 1}",
                    type="unknown",
                    status="invalid",
                    message="Вложенный элемент не является JSON-объектом.",
                )
            )
            continue

        name = str(item.get("name") or f"Элемент #{index + 1}")
        item_type = str(item.get("type") or "unknown")
        item_system = item.get("system")
        if not isinstance(item_system, dict):
            report.item_audit.append(
                ItemAudit(
                    name=name,
                    type=item_type,
                    status="invalid",
                    message="Отсутствует объект system.",
                )
            )
            continue

        count = _activities_count(item_system)
        if count:
            report.item_audit.append(
                ItemAudit(
                    name=name,
                    type=item_type,
                    status="has_activities",
                    message=f"Найдено активностей: {count}.",
                )
            )
            continue

        description = _plain_text(item_system.get("description"))
        has_legacy_mechanics = any(
            key in item_system
            for key in (
                "actionType",
                "activation",
                "attackBonus",
                "damage",
                "save",
                "target",
            )
        )
        if has_legacy_mechanics:
            status = "legacy_mechanics"
            message = (
                "Есть механика старого формата, но нет activities. "
                "Нужна миграция профильным билдером."
            )
        elif any(pattern in name.casefold() for pattern in passive_name_patterns):
            status = "possibly_passive"
            message = (
                "Активностей нет; особенность может оставаться пассивным описанием."
            )
        elif mechanical_words.search(f"{name} {description}"):
            status = "needs_activity"
            message = (
                "Механика присутствует только в названии или описании. "
                "Нужна обработка feat_builder.py."
            )
        else:
            status = "possibly_passive"
            message = (
                "Активностей нет; предмет похож на пассивную особенность. "
                "Описание сохранено."
            )

        report.item_audit.append(ItemAudit(name, item_type, status, message))


def _normalize_token(actor: dict[str, Any], report: BuildReport) -> None:
    token = _dict(actor, "prototypeToken", report, "$")
    _default(token, "name", actor["name"], report, "prototypeToken")
    bar1 = _dict(token, "bar1", report, "prototypeToken")
    _default(bar1, "attribute", "attributes.hp", report, "prototypeToken.bar1")


def _normalize_document_shell(
    actor: dict[str, Any],
    report: BuildReport,
) -> None:
    """Добавляет служебный каркас настоящего экспорта Actor.

    Без ``_stats.systemVersion`` Foundry может принять созданный с нуля JSON
    за экспорт старой версии системы и прогнать лишние миграции. Для NPC-
    заклинателя это, в частности, способно сбросить
    ``system.attributes.spell.level`` до 0 при импорте.
    """
    _default(actor, "img", "icons/svg/mystery-man.svg", report, "$")
    _default(actor, "folder", None, report, "$")
    _default(actor, "flags", {}, report, "$")

    stats = _dict(actor, "_stats", report, "$")
    _default(stats, "coreVersion", FOUNDRY_CORE_VERSION, report, "_stats")
    _default(stats, "systemId", "dnd5e", report, "_stats")
    _default(stats, "systemVersion", DND5E_SYSTEM_VERSION, report, "_stats")
    _default(stats, "createdTime", 0, report, "_stats")
    _default(stats, "modifiedTime", 0, report, "_stats")
    _default(stats, "lastModifiedBy", None, report, "_stats")
    _default(stats, "exportSource", None, report, "_stats")


def normalize_actor(
    source: dict[str, Any],
    source_name: str = "",
    infer_resources: bool = True,
) -> tuple[dict[str, Any], BuildReport]:
    """Возвращает нормализованную копию актёра и отчёт."""
    if not isinstance(source, dict):
        raise ActorBuilderError("Корень JSON должен быть объектом.")

    actor = deepcopy(source)
    report = BuildReport(source=source_name)

    name = actor.get("name")
    if not isinstance(name, str) or not name.strip():
        old = name
        actor["name"] = "Безымянный НПС"
        report.change("$.name", "filled_required_name", old, actor["name"])
    else:
        actor["name"] = name.strip()

    actor_type = actor.get("type")
    if actor_type is None:
        actor["type"] = "npc"
        report.change("$.type", "filled_actor_type", None, "npc")
    elif actor_type != "npc":
        raise ActorBuilderError(
            f"actor_builder.py пока поддерживает только type='npc', получено {actor_type!r}."
        )

    _normalize_document_shell(actor, report)
    system = _dict(actor, "system", report, "$")
    items = _list(actor, "items", report, "$")
    _list(actor, "effects", report, "$")

    _normalize_abilities(system, report)
    _normalize_attributes(system, report)
    _normalize_spell_slots(system, report)
    _normalize_details(system, report)
    _normalize_traits(system, report)
    _normalize_skills(system, report)
    _normalize_currency(system, report)
    if infer_resources:
        _infer_resources(system, items, report)
    _normalize_token(actor, report)
    _audit_items(items, report)

    report.actor_name = actor["name"]
    return actor, report


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except FileNotFoundError as error:
        raise ActorBuilderError(f"Файл не найден: {path}") from error
    except json.JSONDecodeError as error:
        raise ActorBuilderError(
            f"Ошибка JSON в {path}, строка {error.lineno}, столбец {error.colno}: "
            f"{error.msg}"
        ) from error
    except OSError as error:
        raise ActorBuilderError(f"Не удалось прочитать {path}: {error}") from error

    if not isinstance(data, dict):
        raise ActorBuilderError("Корень JSON должен быть объектом.")
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
        raise ActorBuilderError(f"Не удалось записать {path}: {error}") from error


def _default_input() -> Path:
    candidates = (Path("input/npc.json"), Path("npc.json"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _safe_filename(value: str) -> str:
    """Возвращает безопасное имя файла, сохраняя читаемое имя НПС."""
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    filename = re.sub(r"\s+", " ", filename)
    if not filename:
        filename = "Безымянный НПС"
    if filename.upper() in WINDOWS_RESERVED_FILENAMES:
        filename = f"_{filename}"
    return filename


def _default_output(actor_name: str) -> Path:
    filename = _safe_filename(actor_name)
    return Path("output/actors") / f"{filename}_foundry.json"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Нормализует JSON NPC для Foundry VTT 13.351 / D&D5e 5.3.3."
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=None,
        help="Исходный JSON. По умолчанию: input/npc.json или npc.json.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=(
            "Итоговый JSON. По умолчанию имя берётся из поля name: "
            "output/actors/<имя НПС>_foundry.json."
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("logs/actor_builder_report.json"),
        help="Путь к JSON-отчёту.",
    )
    parser.add_argument(
        "--no-infer-resources",
        action="store_true",
        help="Не создавать легендарные ресурсы по названиям особенностей.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        choices=range(1, 9),
        metavar="1-8",
        help="Отступ в итоговом JSON (по умолчанию: 2).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    source_path = args.source or _default_input()

    try:
        source = _load_json(source_path)
        actor, report = normalize_actor(
            source,
            source_name=str(source_path),
            infer_resources=not args.no_infer_resources,
        )
        output_path = args.output or _default_output(actor["name"])
        report.output = str(output_path)
        _atomic_json_write(output_path, actor, args.indent)
        _atomic_json_write(args.report, asdict(report), args.indent)
    except ActorBuilderError as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return 1

    counts: dict[str, int] = {}
    for item in report.item_audit:
        counts[item.status] = counts.get(item.status, 0) + 1

    print(f"Готово: {report.actor_name}")
    print(f"JSON: {output_path}")
    print(f"Отчёт: {args.report}")
    print(f"Исправлений уровня актёра: {len(report.changes)}")
    if counts:
        summary = ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
        print(f"Вложенные предметы: {summary}")
    if report.warnings:
        print(f"Предупреждений: {len(report.warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
