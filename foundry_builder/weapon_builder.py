#!/usr/bin/env python3
"""
Нормализация оружия Foundry VTT 13.351 / D&D5e 5.3.3.

Билдер принимает:
  * полный JSON актёра и обрабатывает все вложенные предметы type="weapon";
  * отдельный JSON оружия type="weapon".

Он сохраняет уже рабочие activities без замены, переносит старые поля атаки
и урона в современную структуру и консервативно извлекает механику из
описания оружия. Для новых атак создаёт Active Effects и привязывает их к
нужным activities.

Запуск:
    python weapon_builder.py output/actors/Мрачный Жнец_foundry.json
    python weapon_builder.py input/weapon.json
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

import midi_compat
import project_config
import enhancement_policy


WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}

DAMAGE_TYPE_PATTERNS = (
    (r"некротическ|necrotic", "necrotic"),
    (r"кислот|acid", "acid"),
    (r"ядом|ядовит|poison", "poison"),
    (r"огнен|огн[её]м|fire", "fire"),
    (r"холод|cold", "cold"),
    (r"электр|молни|lightning", "lightning"),
    (r"громов|thunder", "thunder"),
    (r"силов|force", "force"),
    (r"лучист|radiant", "radiant"),
    (r"психическ|psychic", "psychic"),
    (r"рубящ|slashing", "slashing"),
    (r"колющ|piercing", "piercing"),
    (r"дробящ|bludgeoning", "bludgeoning"),
)

ACTION_TYPE_MAP = {
    "mwak": ("melee", "weapon"),
    "rwak": ("ranged", "weapon"),
    "msak": ("melee", "spell"),
    "rsak": ("ranged", "spell"),
}

ABILITY_ALIASES = {
    "str": "str",
    "strength": "str",
    "сил": "str",
    "силы": "str",
    "dex": "dex",
    "dexterity": "dex",
    "ловк": "dex",
    "ловкости": "dex",
    "con": "con",
    "constitution": "con",
    "тел": "con",
    "телосложения": "con",
    "int": "int",
    "intelligence": "int",
    "инт": "int",
    "интеллекта": "int",
    "wis": "wis",
    "wisdom": "wis",
    "муд": "wis",
    "мудрости": "wis",
    "cha": "cha",
    "charisma": "cha",
    "хар": "cha",
    "харизмы": "cha",
}

ACTIVATION_TYPES = {
    "action",
    "bonus",
    "reaction",
    "legendary",
    "lair",
    "special",
    "none",
}

EFFECT_MODE_ALIASES = {
    "custom": 0,
    "особый": 0,
    "multiply": 1,
    "умножение": 1,
    "add": 2,
    "сложение": 2,
    "добавить": 2,
    "downgrade": 3,
    "понизить": 3,
    "upgrade": 4,
    "повысить": 4,
    "override": 5,
    "заменить": 5,
}

STATUS_ALIASES = {
    "blinded": "blinded",
    "ослеплен": "blinded",
    "charmed": "charmed",
    "очарован": "charmed",
    "deafened": "deafened",
    "оглох": "deafened",
    "exhaustion": "exhaustion",
    "истощение": "exhaustion",
    "frightened": "frightened",
    "испуган": "frightened",
    "grappled": "grappled",
    "схвачен": "grappled",
    "incapacitated": "incapacitated",
    "недееспособен": "incapacitated",
    "invisible": "invisible",
    "невидим": "invisible",
    "paralyzed": "paralyzed",
    "парализован": "paralyzed",
    "petrified": "petrified",
    "окаменел": "petrified",
    "poisoned": "poisoned",
    "отравлен": "poisoned",
    "prone": "prone",
    "сбит с ног": "prone",
    "restrained": "restrained",
    "опутан": "restrained",
    "stunned": "stunned",
    "оглушен": "stunned",
    "ошеломлен": "stunned",
    "unconscious": "unconscious",
    "без сознания": "unconscious",
}

EFFECT_DURATION_UNIT_ALIASES = {
    "turn": "turn",
    "ход": "turn",
    "round": "round",
    "раунд": "round",
    "minute": "minute",
    "минута": "minute",
    "минут": "minute",
    "hour": "hour",
    "час": "hour",
    "часов": "hour",
    "day": "day",
    "день": "day",
    "дней": "day",
}


class WeaponBuilderError(Exception):
    """Ошибка, из-за которой безопасная обработка невозможна."""


@dataclass
class Change:
    path: str
    action: str
    old: Any = None
    new: Any = None


@dataclass
class WeaponResult:
    name: str
    status: str
    activities_before: int
    activities_after: int
    message: str


@dataclass
class BuildReport:
    source: str
    output: str = ""
    changes: list[Change] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    weapons: list[WeaponResult] = field(default_factory=list)

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
        text = text.removeprefix("+")
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
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
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
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
    text = "".join(transliteration.get(character, character) for character in text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "oruzhie"


def _safe_filename(value: str) -> str:
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    filename = re.sub(r"\s+", " ", filename)
    if not filename:
        filename = "Безымянное оружие"
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
    if key in parent and parent[key] is None and value is None:
        return parent[key]
    if key not in parent or parent[key] is None:
        old = parent.get(key)
        parent[key] = deepcopy(value)
        report.change(f"{path}.{key}", "filled_default", old, parent[key])
    return parent[key]


def _damage_type_near(text: str, start: int, end: int) -> str:
    window = text[max(0, start - 45) : min(len(text), end + 65)].casefold()
    for pattern, damage_type in DAMAGE_TYPE_PATTERNS:
        if re.search(pattern, window):
            return damage_type
    return ""


def _normalize_ability(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    text = str(value or "").casefold().replace("ё", "е").strip()
    if text in ABILITY_ALIASES:
        return ABILITY_ALIASES[text]
    for alias, canonical in ABILITY_ALIASES.items():
        if text.startswith(alias):
            return canonical
    return ""


def _normalize_formula(value: Any) -> str:
    formula = str(value or "").strip()
    formula = re.sub(r"(?<=\d)\s*[кК]\s*(?=\d)", "d", formula)
    formula = re.sub(r"\s+", " ", formula)
    return formula


def _formula_components(formula: str) -> tuple[int | None, int, str]:
    compact = re.sub(r"\s+", "", formula.casefold()).replace("к", "d")
    match = re.fullmatch(r"(\d+)d(\d+)(?:([+-])(\d+))?", compact)
    if not match:
        return None, 0, ""
    number, denomination, sign, bonus = match.groups()
    bonus_text = f"{sign}{bonus}" if sign and bonus else ""
    return int(number), int(denomination), bonus_text


def _damage_field(formula: str, damage_type: str) -> dict[str, Any]:
    number, denomination, bonus = _formula_components(formula)
    if number is None:
        return {
            "number": None,
            "denomination": 0,
            "bonus": "",
            "types": [damage_type] if damage_type else [],
            "custom": {"enabled": True, "formula": formula},
            "scaling": {"mode": "whole", "number": None, "formula": ""},
        }
    return {
        "number": number,
        "denomination": denomination,
        "bonus": bonus,
        "types": [damage_type] if damage_type else [],
        "custom": {"enabled": False, "formula": ""},
        "scaling": {"mode": "", "number": None, "formula": ""},
    }


def _empty_damage_field() -> dict[str, Any]:
    return {
        "number": None,
        "denomination": None,
        "bonus": "",
        "types": [],
        "custom": {"enabled": False, "formula": ""},
        "scaling": {"mode": "", "number": None, "formula": ""},
    }


def _base_attack_activity(activity_id: str = "dnd5eactivity000") -> dict[str, Any]:
    activity = {
        "_id": activity_id,
        "type": "attack",
        "activation": {
            "type": "action",
            "value": 1,
            "condition": "",
            "override": False,
        },
        "consumption": {
            "targets": [],
            "scaling": {"allowed": False, "max": ""},
            "spellSlot": True,
        },
        "description": {"chatFlavor": ""},
        "duration": {
            "concentration": False,
            "value": "",
            "units": "inst",
            "special": "",
            "override": False,
        },
        "effects": [],
        "range": {
            "value": "",
            "units": "ft",
            "special": "",
            "override": False,
        },
        "target": {
            "template": {
                "count": "",
                "contiguous": False,
                "type": "",
                "size": "",
                "width": "",
                "height": "",
                "units": "ft",
                "stationary": False,
            },
            "affects": {
                "count": "1",
                "type": "creature",
                "choice": False,
                "special": "",
            },
            "prompt": True,
            "override": False,
        },
        "attack": {
            "ability": "",
            "bonus": "",
            "critical": {"threshold": None},
            "flat": False,
            "type": {"value": "melee", "classification": "weapon"},
        },
        "damage": {
            "critical": {"bonus": ""},
            "includeBase": True,
            "parts": [],
        },
        "uses": {"spent": 0, "recovery": []},
        "sort": 0,
        "name": "",
        "img": None,
        "flags": {},
        "visibility": {
            "level": {},
            "requireAttunement": False,
            "requireIdentification": False,
            "requireMagic": False,
        },
        "useConditionText": "",
        "useConditionReason": "",
        "effectConditionText": "",
        "macroData": {"name": "", "command": ""},
        "ignoreTraits": {
            "idi": False,
            "idr": False,
            "idv": False,
            "ida": False,
            "idm": False,
        },
        "midiProperties": {
            "ignoreTraits": [],
            "triggeredActivityId": "none",
            "triggeredActivityConditionText": "",
            "triggeredActivityTargets": "targets",
            "triggeredActivityRollAs": "self",
            "triggeredActivityConsume": True,
            "triggeredActivityConfigure": True,
            "autoConsume": False,
            "forceConsumeDialog": "default",
            "forceRollDialog": "default",
            "forceDamageDialog": "default",
            "confirmTargets": "default",
            "autoTargetType": "any",
            "autoTargetAction": "default",
            "automationOnly": False,
            "otherActivityCompatible": True,
            "otherActivityAsParentType": True,
            "identifier": "",
            "displayActivityName": False,
            "rollMode": "default",
            "chooseEffects": False,
            "toggleEffect": False,
            "ignoreFullCover": False,
            "removeChatButtons": "default",
            "magicEffect": False,
            "magicDamage": False,
            "noConcentrationCheck": False,
            "skipConcentrationCheck": False,
            "autoCEEffects": "default",
        },
        "isOverTimeFlag": False,
        "overTimeProperties": {
            "saveRemoves": True,
            "rollAs": "target",
            "preRemoveConditionText": "",
            "postRemoveConditionText": "",
        },
        "otherActivityId": "",
        "otherActivityAsParentType": True,
        "attackMode": "oneHanded",
        "ammunition": "",
        "otherActivityUuid": "",
        "attackRollPerTarget": "default",
        "fumbleThreshold": 1,
    }
    midi_compat.normalize_activity(activity)
    return activity


def _base_save_activity(activity_id: str = "dnd5eactivity100") -> dict[str, Any]:
    activity = _base_attack_activity(activity_id)
    activity["type"] = "save"
    activity.pop("attack", None)
    activity.pop("attackMode", None)
    activity.pop("ammunition", None)
    activity.pop("otherActivityUuid", None)
    activity.pop("attackRollPerTarget", None)
    activity.pop("fumbleThreshold", None)
    activity["damage"] = {
        "onSave": "none",
        "parts": [],
        "critical": {"allow": False},
    }
    activity["save"] = {
        "ability": [],
        "dc": {"calculation": "", "formula": ""},
    }
    activity["friendlySave"] = "default"
    return activity


def _base_utility_activity(activity_id: str = "dnd5eactivity100") -> dict[str, Any]:
    activity = _base_save_activity(activity_id)
    activity["type"] = "utility"
    activity.pop("damage", None)
    activity.pop("save", None)
    activity.pop("friendlySave", None)
    activity["roll"] = {
        "formula": "",
        "name": "",
        "prompt": False,
        "visible": False,
    }
    return activity


def _base_damage_activity(activity_id: str = "dnd5eactivity100") -> dict[str, Any]:
    activity = _base_save_activity(activity_id)
    activity["type"] = "damage"
    activity.pop("save", None)
    activity.pop("friendlySave", None)
    activity["damage"] = {
        "critical": {"allow": False},
        "parts": [],
    }
    return activity


def _healing_field(formula: str, healing_type: str) -> dict[str, Any]:
    field = _damage_field(formula, healing_type or "healing")
    field["scaling"] = {"mode": "whole", "number": None, "formula": ""}
    return field


def _base_heal_activity(activity_id: str = "dnd5eactivity100") -> dict[str, Any]:
    activity = _base_save_activity(activity_id)
    activity["type"] = "heal"
    activity.pop("damage", None)
    activity.pop("save", None)
    activity.pop("friendlySave", None)
    activity["range"].pop("value", None)
    activity["range"]["units"] = "self"
    activity["target"]["affects"]["type"] = "self"
    activity["healing"] = _healing_field("", "healing")
    activity["healing"]["custom"] = {"enabled": False, "formula": ""}
    return activity


def _extract_explicit_mechanics(weapon: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        weapon.get("mechanics"),
        (weapon.get("system") or {}).get("mechanics")
        if isinstance(weapon.get("system"), dict)
        else None,
    ]
    flags = weapon.get("flags")
    if isinstance(flags, dict):
        namespace = flags.get("foundry-content-generator")
        if isinstance(namespace, dict):
            candidates.append(namespace.get("mechanics"))
    for candidate in candidates:
        if isinstance(candidate, dict):
            return deepcopy(candidate)
    return {}


def _legacy_damage_parts(system: dict[str, Any]) -> list[dict[str, str]]:
    damage = system.get("damage")
    if not isinstance(damage, dict):
        return []
    parts = damage.get("parts")
    if not isinstance(parts, list):
        return []
    result: list[dict[str, str]] = []
    for part in parts:
        formula = ""
        damage_type = ""
        if isinstance(part, (list, tuple)) and part:
            formula = _normalize_formula(part[0])
            damage_type = str(part[1] if len(part) > 1 else "")
        elif isinstance(part, dict):
            formula = _normalize_formula(
                part.get("formula")
                or part.get("value")
                or (part.get("custom") or {}).get("formula")
            )
            types = part.get("types")
            if isinstance(types, list) and types:
                damage_type = str(types[0])
            else:
                damage_type = str(part.get("type") or "")
        if formula:
            result.append({"formula": formula, "type": damage_type})
    return result


def _current_base_damage(system: dict[str, Any]) -> list[dict[str, str]]:
    damage = system.get("damage")
    if not isinstance(damage, dict):
        return []
    base = damage.get("base")
    if not isinstance(base, dict):
        return []
    custom = base.get("custom")
    if isinstance(custom, dict) and custom.get("enabled") and custom.get("formula"):
        formula = _normalize_formula(custom["formula"])
    else:
        number = base.get("number")
        denomination = base.get("denomination")
        if not _is_number(number) or not _is_number(denomination):
            return []
        formula = f"{int(number)}d{int(denomination)}"
        bonus = str(base.get("bonus") or "").strip()
        if bonus:
            formula += bonus if bonus.startswith(("+", "-")) else f"+{bonus}"
    types = base.get("types")
    damage_type = str(types[0]) if isinstance(types, list) and types else ""
    return [{"formula": formula, "type": damage_type}]


def _description_damage(text: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    dice_pattern = re.compile(
        r"(?<![а-яa-z0-9])(\d+)\s*[кd]\s*(\d+)(?:\s*([+-])\s*(\d+))?",
        re.IGNORECASE,
    )
    for match in dice_pattern.finditer(text.casefold()):
        number, denomination, sign, bonus = match.groups()
        formula = f"{number}d{denomination}"
        if sign and bonus:
            formula += f"{sign}{bonus}"
        local_context = text[
            max(0, match.start() - 45) : min(len(text), match.end() + 65)
        ]
        if not re.search(r"урон|поврежден|damage", local_context, re.IGNORECASE):
            continue
        damage_type = _damage_type_near(text, match.start(), match.end())
        key = (formula, damage_type)
        if key not in seen:
            seen.add(key)
            result.append({"formula": formula, "type": damage_type})
    return result


def _attack_type(system: dict[str, Any], explicit: dict[str, Any]) -> dict[str, str]:
    attack = explicit.get("attack")
    if isinstance(attack, dict):
        value = str(attack.get("type") or attack.get("value") or "")
        classification = str(attack.get("classification") or "")
        if value in {"melee", "ranged"}:
            return {
                "value": value,
                "classification": classification or "weapon",
            }

    action_type = str(system.get("actionType") or "")
    if action_type in ACTION_TYPE_MAP:
        value, classification = ACTION_TYPE_MAP[action_type]
        return {"value": value, "classification": classification}

    weapon_type = system.get("type")
    if isinstance(weapon_type, dict):
        value = str(weapon_type.get("value") or "")
        if value.endswith("R"):
            return {"value": "ranged", "classification": "weapon"}
    return {"value": "melee", "classification": "weapon"}


def _attack_bonus(
    system: dict[str, Any],
    explicit: dict[str, Any],
    text: str,
) -> tuple[str, bool]:
    attack = explicit.get("attack")
    if isinstance(attack, dict) and attack.get("bonus") not in (None, ""):
        value = str(attack["bonus"]).strip()
        bonus = value if value.startswith(("+", "-")) else f"+{value}"
        return bonus, bool(attack.get("flat", True))

    legacy_attack = system.get("attack")
    if isinstance(legacy_attack, dict) and legacy_attack.get("bonus") not in (None, ""):
        value = str(legacy_attack["bonus"]).strip()
        bonus = value if value.startswith(("+", "-")) else f"+{value}"
        return bonus, bool(legacy_attack.get("flat", False))

    value = system.get("attackBonus")
    if value not in (None, ""):
        text_value = str(value).strip()
        bonus = text_value if text_value.startswith(("+", "-")) else f"+{text_value}"
        return bonus, True

    match = re.search(
        r"([+-]\s*\d+)\s*(?:к\s+попадан|to\s+hit)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).replace(" ", ""), True
    return "", False


def _extract_save(
    text: str,
    system: dict[str, Any],
    explicit: dict[str, Any],
) -> dict[str, Any]:
    candidate = explicit.get("save")
    if not isinstance(candidate, dict):
        legacy = system.get("save")
        candidate = legacy if isinstance(legacy, dict) else {}
    if candidate:
        ability = _normalize_ability(
            candidate.get("ability")
            or candidate.get("abilities")
            or candidate.get("value")
        )
        dc_data = candidate.get("dc")
        if isinstance(dc_data, dict):
            dc = _integer(dc_data.get("formula") or dc_data.get("value"), 0)
        else:
            dc = _integer(dc_data, 0)
        if ability and dc:
            result = {"ability": ability, "dc": dc}
            damage = candidate.get("damage")
            if isinstance(damage, list):
                result["damage"] = deepcopy(damage)
            if candidate.get("on_save"):
                result["on_save"] = str(candidate["on_save"])
            return result

    normalized = text.casefold().replace("ё", "е")
    patterns = (
        r"(?:сл|dc)\s*(\d+)[^.;]{0,70}?"
        r"(сил\w*|ловк\w*|телослож\w*|интеллект\w*|мудрост\w*|"
        r"харизм\w*|strength|dexterity|constitution|intelligence|wisdom|charisma)"
        r"[^.;]{0,40}?(?:спасброс|saving throw)",
        r"(?:спасброс\w*|saving throw)[^.;]{0,45}?"
        r"(сил\w*|ловк\w*|телослож\w*|интеллект\w*|мудрост\w*|"
        r"харизм\w*|strength|dexterity|constitution|intelligence|wisdom|charisma)"
        r"[^.;]{0,30}?(?:сл|dc)\s*(\d+)",
        r"(сил\w*|ловк\w*|телослож\w*|интеллект\w*|мудрост\w*|"
        r"харизм\w*|strength|dexterity|constitution|intelligence|wisdom|charisma)"
        r"[^.;]{0,30}?(?:спасброс\w*|saving throw)[^.;]{0,30}?(?:сл|dc)\s*(\d+)",
        r"(?:dc)\s*(\d+)\s*"
        r"(strength|dexterity|constitution|intelligence|wisdom|charisma)"
        r"[^.;]{0,30}?saving throw",
    )
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, normalized, re.IGNORECASE)
        if not match:
            continue
        first, second = match.groups()
        if index in {0, 3}:
            dc, ability_text = first, second
        else:
            ability_text, dc = first, second
        ability = _normalize_ability(ability_text)
        if ability:
            return {"ability": ability, "dc": int(dc)}
    return {}


def _on_save(text: str) -> str:
    normalized = text.casefold().replace("ё", "е")
    patterns = (
        r"(?:при успехе|успех)[^.]{0,100}(?:половин|вдвое меньше)",
        r"(?:половин|вдвое меньше)[^.]{0,100}(?:при успехе|успешн)",
        r"(?:successful save|on a success)[^.]{0,100}(?:half as much|half damage)",
        r"(?:half as much|half damage)[^.]{0,100}(?:successful save|on a success)",
    )
    return "half" if any(re.search(pattern, normalized) for pattern in patterns) else "none"


def _activation_from_text(text: str) -> dict[str, Any]:
    normalized = text.casefold().replace("ё", "е")
    if "действие логова" in normalized or "lair action" in normalized:
        return {"type": "lair", "value": 1, "condition": ""}
    legendary = re.search(
        r"(?:легендарн\w*\s+действ\w*|legendary action).*?"
        r"(?:стоимост\w*|costs?|затрачива\w*)?\s*\(?\s*(\d+)\s+"
        r"(?:действ|action)",
        normalized,
    )
    if legendary:
        return {
            "type": "legendary",
            "value": int(legendary.group(1)),
            "condition": "",
        }
    if "легендарн" in normalized or "legendary" in normalized:
        return {"type": "legendary", "value": 1, "condition": ""}
    if "бонусн" in normalized or "bonus action" in normalized:
        return {"type": "bonus", "value": 1, "condition": ""}
    if "реакци" in normalized or "reaction" in normalized:
        return {"type": "reaction", "value": 1, "condition": ""}
    if "в начале" in normalized or "в конце" in normalized:
        return {"type": "special", "value": None, "condition": ""}
    return {"type": "action", "value": 1, "condition": ""}


def _range_and_target(
    system: dict[str, Any],
    explicit: dict[str, Any],
    text: str,
    attack_type: str,
) -> dict[str, Any]:
    current = system.get("range")
    current = current if isinstance(current, dict) else {}
    result: dict[str, Any] = {
        "value": current.get("value"),
        "long": current.get("long"),
        "reach": current.get("reach"),
        "units": current.get("units") or "ft",
        "count": "1",
        "target_type": "creature",
    }

    explicit_range = explicit.get("range")
    if isinstance(explicit_range, dict):
        for key in ("value", "long", "reach", "units"):
            if key in explicit_range:
                result[key] = explicit_range[key]

    explicit_target = explicit.get("target")
    if isinstance(explicit_target, dict):
        count = explicit_target.get("count", explicit_target.get("value"))
        if count not in (None, ""):
            result["count"] = str(count)
        target_type = explicit_target.get("type")
        if target_type:
            result["target_type"] = str(target_type)

    if attack_type == "melee" and result["reach"] in (None, ""):
        match = re.search(
            r"(?:досягаемост\w*|reach)\s*(\d+)\s*(?:фут|feet|foot|ft)",
            text,
            re.IGNORECASE,
        )
        result["reach"] = int(match.group(1)) if match else 5
    if attack_type == "ranged" and result["value"] in (None, ""):
        match = re.search(
            r"(?:дистанци\w*|range)\s*(\d+)(?:\s*/\s*(\d+))?\s*(?:фут|feet|foot|ft)",
            text,
            re.IGNORECASE,
        )
        if match:
            result["value"] = int(match.group(1))
            if match.group(2):
                result["long"] = int(match.group(2))
    return result


def _actor_modifiers(actor_system: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(actor_system, dict):
        return {}
    abilities = actor_system.get("abilities")
    if not isinstance(abilities, dict):
        return {}
    result: dict[str, int] = {}
    for ability in ("str", "dex"):
        data = abilities.get(ability)
        if not isinstance(data, dict):
            continue
        value = _integer(data.get("value"), 10)
        result[ability] = (value - 10) // 2
    return result


def _select_damage_ability(
    actor_system: dict[str, Any] | None,
    attack_type: str,
    first_formula: str,
) -> tuple[str, str]:
    """Возвращает способность и формулу без уже включённого модификатора."""
    number, denomination, bonus = _formula_components(first_formula)
    if number is None or not bonus:
        preferred = "str" if attack_type == "melee" else "dex"
        if preferred in _actor_modifiers(actor_system):
            return preferred, first_formula
        return "", first_formula

    modifiers = _actor_modifiers(actor_system)
    bonus_value = _integer(bonus)
    order = ("str", "dex") if attack_type == "melee" else ("dex", "str")
    for ability in order:
        if modifiers.get(ability) == bonus_value:
            return ability, f"{number}d{denomination}"

    # Неизвестный фиксированный бонус сохраняется, а модификатор способности
    # отключается, чтобы Foundry не прибавил его второй раз.
    return "none", first_formula


def _merged_mechanics(
    weapon: dict[str, Any],
    actor_system: dict[str, Any] | None,
) -> dict[str, Any]:
    system = weapon.get("system")
    if not isinstance(system, dict):
        system = {}
    text = _plain_text(system.get("description"))
    explicit = _extract_explicit_mechanics(weapon)
    activity_specs = explicit.get("activities")
    if not isinstance(activity_specs, list):
        activity_specs = []

    damage = explicit.get("damage")
    if not isinstance(damage, list):
        damage = _legacy_damage_parts(system)
    if not damage:
        damage = _current_base_damage(system)
    if not damage:
        for spec in activity_specs:
            if not isinstance(spec, dict) or spec.get("type") != "attack":
                continue
            spec_damage = spec.get("damage")
            if isinstance(spec_damage, list) and spec_damage:
                damage = deepcopy(spec_damage)
                break
    if not damage:
        damage = _description_damage(text)

    normalized_damage: list[dict[str, str]] = []
    for part in damage:
        if not isinstance(part, dict):
            continue
        formula = _normalize_formula(part.get("formula"))
        if formula:
            normalized_damage.append(
                {"formula": formula, "type": str(part.get("type") or "")}
            )

    attack_kind = _attack_type(system, explicit)
    bonus, flat = _attack_bonus(system, explicit, text)
    attack_evidence = bool(
        isinstance(explicit.get("attack"), dict)
        or str(system.get("actionType") or "") in ACTION_TYPE_MAP
        or system.get("attackBonus") not in (None, "")
        or re.search(
            r"(?:\[\[/attack|[+-]\s*\d+\s*(?:к\s+попадан|to hit)|"
            r"бросок\s+атаки|attack roll)",
            text,
            re.IGNORECASE,
        )
    )
    ability = ""
    if isinstance(explicit.get("attack"), dict):
        ability = str(explicit["attack"].get("ability") or "")
    # Явные activities уже содержат полный контракт атаки. Не пытайся
    # повторно вывести модификатор владельца из первого компонента урона:
    # для фиксированной атаки NPC это ошибочно превращало, например,
    # ``1d8+7`` в ``1d8`` перед переносом формулы в system.damage.base.
    if normalized_damage and not ability and not activity_specs:
        ability, normalized_damage[0]["formula"] = _select_damage_ability(
            actor_system,
            attack_kind["value"],
            normalized_damage[0]["formula"],
        )

    activation = explicit.get("activation")
    if not isinstance(activation, dict):
        legacy = system.get("activation")
        if isinstance(legacy, dict):
            activation = {
                "type": legacy.get("type") or "action",
                "value": legacy.get("value") or legacy.get("cost") or 1,
                "condition": legacy.get("condition") or "",
            }
        else:
            activation = _activation_from_text(text)

    save = _extract_save(text, system, explicit)
    explicit_attack = (
        explicit.get("attack")
        if isinstance(explicit.get("attack"), dict)
        else {}
    )
    attack_result = {
        "type": attack_kind["value"],
        "classification": attack_kind["classification"],
        "ability": ability,
        "bonus": bonus,
        "flat": flat,
    }
    for key in ("critical", "critical_threshold"):
        if key in explicit_attack:
            attack_result[key] = deepcopy(explicit_attack[key])

    return {
        "attack": attack_result,
        "damage": normalized_damage,
        "range": _range_and_target(
            system, explicit, text, attack_kind["value"]
        ),
        "activation": activation,
        "save": save,
        "on_save": str(explicit.get("on_save") or _on_save(text)),
        "activities": deepcopy(activity_specs),
        "uses": deepcopy(explicit.get("uses"))
        if isinstance(explicit.get("uses"), dict)
        else {},
        "effects": deepcopy(explicit.get("effects"))
        if isinstance(explicit.get("effects"), list)
        else [],
        "duration": deepcopy(explicit.get("duration"))
        if isinstance(explicit.get("duration"), dict)
        else {},
        "activity_type": str(explicit.get("activity_type") or ""),
        "target": deepcopy(explicit.get("target")),
        "consumption": deepcopy(explicit.get("consumption")),
        "roll": deepcopy(explicit.get("roll")),
        "healing": deepcopy(explicit.get("healing")),
        "description": deepcopy(
            explicit.get("description", explicit.get("chat_flavor"))
        ),
        "chat_flavor": deepcopy(explicit.get("chat_flavor")),
        "midi_properties": deepcopy(explicit.get("midi_properties")),
        "auto_target_action": str(
            explicit.get("auto_target_action") or ""
        ),
        "auto_target_type": str(explicit.get("auto_target_type") or ""),
        "visibility": deepcopy(explicit.get("visibility")),
        "include_base": explicit.get("include_base"),
        "attack_mode": str(explicit.get("attack_mode") or ""),
        "use_condition_text": str(
            explicit.get("use_condition_text") or ""
        ),
        "use_condition_reason": str(
            explicit.get("use_condition_reason") or ""
        ),
        "effect_condition_text": str(
            explicit.get("effect_condition_text") or ""
        ),
        "macro_data": deepcopy(explicit.get("macro_data")),
        "ignore_traits": deepcopy(explicit.get("ignore_traits")),
        "is_over_time": explicit.get("is_over_time"),
        "over_time_properties": deepcopy(
            explicit.get("over_time_properties")
        ),
        "attack_evidence": attack_evidence,
        "text": text,
    }


def _normalize_damage_container(
    system: dict[str, Any],
    report: BuildReport,
    path: str,
) -> dict[str, Any]:
    damage = _ensure_dict(system, "damage", report, path)
    base = damage.get("base")
    if not isinstance(base, dict):
        old = base
        damage["base"] = _empty_damage_field()
        report.change(
            f"{path}.damage.base",
            "created_damage_base",
            old,
            deepcopy(damage["base"]),
        )
    else:
        _default(base, "number", None, report, f"{path}.damage.base")
        _default(base, "denomination", None, report, f"{path}.damage.base")
        _default(base, "bonus", "", report, f"{path}.damage.base")
        _default(base, "types", [], report, f"{path}.damage.base")
        custom = _ensure_dict(base, "custom", report, f"{path}.damage.base")
        _default(custom, "enabled", False, report, f"{path}.damage.base.custom")
        _default(custom, "formula", "", report, f"{path}.damage.base.custom")
        scaling = _ensure_dict(base, "scaling", report, f"{path}.damage.base")
        _default(scaling, "mode", "", report, f"{path}.damage.base.scaling")
        _default(scaling, "number", None, report, f"{path}.damage.base.scaling")
        _default(scaling, "formula", "", report, f"{path}.damage.base.scaling")

    versatile = damage.get("versatile")
    if not isinstance(versatile, dict):
        old = versatile
        damage["versatile"] = _empty_damage_field()
        report.change(
            f"{path}.damage.versatile",
            "created_versatile_damage",
            old,
            deepcopy(damage["versatile"]),
        )
    return damage


def _write_base_damage(
    system: dict[str, Any],
    first_damage: dict[str, str],
    report: BuildReport,
    path: str,
) -> None:
    damage = _normalize_damage_container(system, report, path)
    base = damage["base"]
    new_base = _damage_field(first_damage["formula"], first_damage["type"])
    if base != new_base:
        old = deepcopy(base)
        damage["base"] = new_base
        report.change(
            f"{path}.damage.base",
            "migrated_base_damage",
            old,
            deepcopy(new_base),
        )
    if "parts" in damage:
        old_parts = damage.pop("parts")
        report.change(
            f"{path}.damage.parts",
            "removed_legacy_damage_parts",
            old_parts,
            None,
        )


def _apply_activity_common(
    activity: dict[str, Any],
    mechanics: dict[str, Any],
) -> None:
    activity["name"] = str(mechanics.get("activity_name") or "")

    activation = mechanics.get("activation")
    if isinstance(activation, dict):
        activation_type = str(activation.get("type") or "action")
        if activation_type not in ACTIVATION_TYPES:
            activation_type = "action"
        activity["activation"]["type"] = activation_type
        value = activation.get("value")
        activity["activation"]["value"] = (
            None
            if value is None and activation_type in {"special", "none"}
            else _integer(value, 1)
        )
        activity["activation"]["condition"] = str(
            activation.get("condition") or ""
        )

    duration = mechanics.get("duration")
    if isinstance(duration, dict):
        activity["duration"]["value"] = str(duration.get("value") or "")
        activity["duration"]["units"] = str(duration.get("units") or "inst")
        activity["duration"]["special"] = str(duration.get("special") or "")
        activity["duration"]["concentration"] = bool(
            duration.get("concentration", False)
        )

    range_data = mechanics.get("range")
    if isinstance(range_data, dict):
        activity_type = activity.get("type")
        attack_type = (
            ((activity.get("attack") or {}).get("type") or {}).get("value")
            if activity_type == "attack"
            else ""
        )
        attack_range = (
            range_data.get("reach")
            if attack_type == "melee"
            else range_data.get("value")
        )
        if attack_range in (None, "") and activity_type != "attack":
            attack_range = range_data.get("reach")
        activity["range"]["value"] = (
            str(attack_range) if attack_range not in (None, "") else ""
        )
        activity["range"]["units"] = str(range_data.get("units") or "ft")
        activity["range"]["special"] = str(range_data.get("special") or "")
        activity["target"]["affects"]["count"] = str(
            range_data.get("count") or ""
        )
        activity["target"]["affects"]["type"] = str(
            range_data.get("target_type") or "creature"
        )
        template = range_data.get("template")
        if isinstance(template, dict):
            for key in (
                "count",
                "contiguous",
                "type",
                "size",
                "width",
                "height",
                "units",
                "stationary",
            ):
                if key in template:
                    value = template[key]
                    activity["target"]["template"][key] = (
                        str(value)
                        if key in {"count", "size", "width", "height"}
                        and value is not None
                        else value
                    )

    target_data = mechanics.get("target")
    if isinstance(target_data, dict):
        affects = target_data.get("affects")
        if isinstance(affects, dict):
            for key in ("count", "type", "choice", "special"):
                if key in affects:
                    value = affects[key]
                    activity["target"]["affects"][key] = (
                        str(value) if key == "count" and value is not None else value
                    )
        template = target_data.get("template")
        if isinstance(template, dict):
            for key in activity["target"]["template"]:
                if key in template:
                    value = template[key]
                    activity["target"]["template"][key] = (
                        str(value)
                        if key in {"count", "size", "width", "height"}
                        and value is not None
                        else value
                    )
        if "prompt" in target_data:
            activity["target"]["prompt"] = bool(target_data["prompt"])

    consumption = mechanics.get("consumption")
    if isinstance(consumption, list):
        targets: list[dict[str, Any]] = []
        for target in consumption:
            if not isinstance(target, dict) or not target.get("type"):
                continue
            normalized = deepcopy(target)
            normalized["type"] = str(normalized["type"])
            normalized["target"] = str(normalized.get("target") or "")
            normalized["value"] = str(normalized.get("value") or "1")
            scaling = normalized.get("scaling")
            if not isinstance(scaling, dict):
                normalized["scaling"] = {"mode": "", "formula": ""}
            targets.append(normalized)
        activity["consumption"]["targets"] = targets

    uses = mechanics.get("uses")
    if isinstance(uses, dict):
        maximum = uses.get("max")
        if maximum not in (None, ""):
            activity["uses"]["max"] = str(maximum)
        activity["uses"]["spent"] = _integer(uses.get("spent"), 0)
        recovery = uses.get("recovery")
        if isinstance(recovery, list):
            activity["uses"]["recovery"] = deepcopy(recovery)
        if (
            activity["uses"].get("max") not in (None, "")
            and not activity["consumption"]["targets"]
        ):
            activity["consumption"]["targets"] = [
                {
                    "type": "activityUses",
                    "target": "",
                    "value": "1",
                    "scaling": {"mode": "", "formula": ""},
                }
            ]

    description = mechanics.get("description")
    if isinstance(description, dict):
        activity["description"]["chatFlavor"] = str(
            description.get("chatFlavor")
            or description.get("chat")
            or description.get("value")
            or ""
        )
    elif description not in (None, ""):
        activity["description"]["chatFlavor"] = str(description)
    elif mechanics.get("chat_flavor") not in (None, ""):
        activity["description"]["chatFlavor"] = str(mechanics["chat_flavor"])

    visibility = mechanics.get("visibility")
    if isinstance(visibility, dict):
        for key in (
            "requireAttunement",
            "requireIdentification",
            "requireMagic",
        ):
            if key in visibility:
                activity["visibility"][key] = bool(visibility[key])
    if mechanics.get("auto_target_action"):
        activity["midiProperties"]["autoTargetAction"] = str(
            mechanics["auto_target_action"]
        )
    if mechanics.get("auto_target_type"):
        activity["midiProperties"]["autoTargetType"] = str(
            mechanics["auto_target_type"]
        )
    midi_compat.apply_activity_mechanics(activity, mechanics)


def _build_attack_activity(
    mechanics: dict[str, Any],
    activity_id: str = "dnd5eactivity000",
) -> dict[str, Any] | None:
    # WEAPON_OWNER_DAMAGE_FIX:
    # Для оружия владельца magicalBonus остаётся пустым в attack.bonus,
    # но входит в первую формулу урона вместе с @mod. Так D&D5e не удваивает
    # бонус атаки и одновременно корректно бросает полный базовый урон.
    damage = mechanics.get("damage")
    attack = mechanics.get("attack")
    if not isinstance(damage, list) or not damage or not isinstance(attack, dict):
        return None

    activity = _base_attack_activity(activity_id)

    activity["attack"]["ability"] = str(attack.get("ability") or "")
    activity["attack"]["bonus"] = str(attack.get("bonus") or "")
    activity["attack"]["flat"] = bool(attack.get("flat"))
    activity["attack"]["type"] = {
        "value": str(attack.get("type") or "melee"),
        "classification": str(attack.get("classification") or "weapon"),
    }
    critical = attack.get("critical")
    if isinstance(critical, dict):
        threshold = critical.get("threshold")
        if threshold not in (None, ""):
            activity["attack"]["critical"]["threshold"] = _integer(threshold)
        activity["damage"]["critical"]["bonus"] = str(
            critical.get("bonus") or ""
        )
    elif attack.get("critical_threshold") not in (None, ""):
        activity["attack"]["critical"]["threshold"] = _integer(
            attack["critical_threshold"]
        )
    raw_include_base = mechanics.get("include_base")
    include_base = (
        True if raw_include_base is None else bool(raw_include_base)
    )
    activity["damage"]["includeBase"] = include_base
    activity["attackMode"] = str(mechanics.get("attack_mode") or "oneHanded")

    _apply_activity_common(activity, mechanics)
    if not activity["target"]["affects"]["count"]:
        activity["target"]["affects"]["count"] = "1"

    magical_bonus = _number(mechanics.get("_item_magical_bonus"), 0)
    magical_bonus_text = (
        str(int(magical_bonus))
        if isinstance(magical_bonus, float) and magical_bonus.is_integer()
        else str(magical_bonus)
    )

    activity_damage = damage[1:] if include_base else damage
    for index, damage_part in enumerate(activity_damage):
        if not isinstance(damage_part, dict):
            continue

        formula = str(damage_part.get("formula") or "")
        field = _damage_field(
            formula,
            str(damage_part.get("type") or ""),
        )
        if index == 0 and not include_base and not activity["attack"]["flat"]:
            additions: list[str] = []
            existing_bonus = str(field.get("bonus") or "").strip()

            if "@mod" not in formula and "@mod" not in existing_bonus:
                additions.append("@mod")
            if magical_bonus:
                additions.append(magical_bonus_text)
            if existing_bonus:
                additions.append(existing_bonus)

            if field.get("custom", {}).get("enabled"):
                custom_formula = str(
                    field.get("custom", {}).get("formula") or formula
                ).strip()
                suffix = " + ".join(additions)
                if suffix:
                    field["custom"]["formula"] = (
                        f"({custom_formula}) + {suffix}"
                        if custom_formula
                        else suffix
                    )
            elif additions:
                field["bonus"] = " + ".join(additions)

        activity["damage"]["parts"].append(field)
    return activity


def _build_save_activity(
    mechanics: dict[str, Any],
    activity_id: str = "dnd5eactivity100",
) -> dict[str, Any] | None:
    save = mechanics.get("save")
    if not isinstance(save, dict):
        return None
    ability = _normalize_ability(save.get("ability"))
    dc = _integer(save.get("dc"), 0)
    if not ability or not dc:
        return None

    activity = _base_save_activity(activity_id)
    activity["name"] = str(mechanics.get("activity_name") or "")
    _apply_activity_common(activity, mechanics)
    activity["save"]["ability"] = [ability]
    activity["save"]["dc"]["formula"] = str(dc)
    activity["damage"]["onSave"] = str(
        mechanics.get("on_save") or save.get("on_save") or "none"
    )
    damage = mechanics.get("damage")
    if not isinstance(damage, list):
        damage = []
    for part in damage:
        if not isinstance(part, dict) or not part.get("formula"):
            continue
        activity["damage"]["parts"].append(
            _damage_field(
                str(part["formula"]),
                str(part.get("type") or ""),
            )
        )
    return activity


def _build_utility_activity(
    mechanics: dict[str, Any],
    activity_id: str = "dnd5eactivity100",
) -> dict[str, Any]:
    activity = _base_utility_activity(activity_id)
    activity["name"] = str(mechanics.get("activity_name") or "")
    _apply_activity_common(activity, mechanics)
    roll = mechanics.get("roll")
    if isinstance(roll, dict):
        activity["roll"].update(
            {
                key: value
                for key, value in roll.items()
                if key in activity["roll"]
            }
        )
    return activity


def _build_damage_activity(
    mechanics: dict[str, Any],
    activity_id: str = "dnd5eactivity100",
) -> dict[str, Any] | None:
    damage = mechanics.get("damage")
    if not isinstance(damage, list) or not damage:
        return None
    activity = _base_damage_activity(activity_id)
    _apply_activity_common(activity, mechanics)
    for part in damage:
        if not isinstance(part, dict):
            continue
        formula = str(part.get("formula") or "").strip()
        if formula:
            activity["damage"]["parts"].append(
                _damage_field(formula, str(part.get("type") or ""))
            )
    return activity if activity["damage"]["parts"] else None


def _build_heal_activity(
    mechanics: dict[str, Any],
    activity_id: str = "dnd5eactivity100",
) -> dict[str, Any] | None:
    healing = mechanics.get("healing")
    if isinstance(healing, str):
        healing = {"formula": healing, "type": "healing"}
    if not isinstance(healing, dict):
        return None
    formula = str(healing.get("formula") or "").strip()
    if not formula:
        return None
    activity = _base_heal_activity(activity_id)
    _apply_activity_common(activity, mechanics)
    activity["healing"] = _healing_field(
        formula,
        str(healing.get("type") or "healing"),
    )
    return activity


def _activity_id(index: int) -> str:
    # Foundry document IDs must contain exactly 16 alphanumeric characters.
    # The old ``index * 100`` scheme overflowed to 17 characters at index 10
    # (``dnd5eactivity1000``), causing complex items to fail import silently.
    if index < 0 or index > 999:
        raise ValueError("Поддерживается не более 1000 активностей на один предмет.")
    return f"dnd5eactivity{index:03d}"


def _effect_id(index: int) -> str:
    return f"dnd5eeffect{index:05d}"


def _normalize_effect_mode(value: Any) -> int:
    if _is_number(value):
        return max(0, min(5, _integer(value, 2)))
    text = str(value or "add").casefold().replace("ё", "е").strip()
    return EFFECT_MODE_ALIASES.get(text, 2)


def _normalize_statuses(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [
            item.strip()
            for item in re.split(r"[,;/]+", value)
            if item.strip()
        ]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    result: list[str] = []
    for item in values:
        text = str(item or "").casefold().replace("ё", "е").strip()
        status = STATUS_ALIASES.get(text, text)
        if status and status not in result:
            result.append(status)
    return result


def _effect_duration(value: Any) -> dict[str, Any]:
    result = {
        "startTime": None,
        "seconds": None,
        "combat": None,
        "rounds": None,
        "turns": None,
        "startRound": None,
        "startTurn": None,
    }
    if not isinstance(value, dict):
        return result
    if any(key in value for key in ("seconds", "rounds", "turns")):
        for key in result:
            if key in value:
                result[key] = deepcopy(value[key])
        return result
    number = _integer(value.get("value"), 0)
    units_text = str(value.get("units") or "").casefold().replace("ё", "е").strip()
    units = EFFECT_DURATION_UNIT_ALIASES.get(units_text, units_text)
    if number <= 0:
        return result
    if units == "turn":
        result["turns"] = number
    elif units == "round":
        result["rounds"] = number
    elif units == "minute":
        result["seconds"] = number * 60
    elif units == "hour":
        result["seconds"] = number * 3600
    elif units == "day":
        result["seconds"] = number * 86400
    return result


def _effect_changes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for change in value:
        if not isinstance(change, dict):
            continue
        key = str(change.get("key") or "").strip()
        if not key:
            continue
        result.append(
            {
                "key": key,
                "mode": _normalize_effect_mode(change.get("mode")),
                "value": str(change.get("value") or ""),
                "priority": (
                    _integer(change.get("priority"))
                    if change.get("priority") not in (None, "")
                    else None
                ),
            }
        )
    return result


def _build_effect(
    spec: dict[str, Any],
    index: int,
    weapon_name: str,
    default_duration: dict[str, Any],
) -> dict[str, Any]:
    raw_id = str(spec.get("_id") or "").strip()
    effect_id = (
        raw_id
        if re.fullmatch(r"[A-Za-z0-9]{16}", raw_id)
        else _effect_id(index)
    )
    flags = midi_compat.effect_flags(spec)
    duration = spec.get("duration")
    if not isinstance(duration, dict):
        duration = default_duration
    return {
        "_id": effect_id,
        "name": str(spec.get("name") or weapon_name),
        "img": str(spec.get("img") or ""),
        "type": "base",
        "system": {},
        "changes": _effect_changes(spec.get("changes")),
        "disabled": bool(spec.get("disabled", False)),
        "duration": _effect_duration(duration),
        "description": str(spec.get("description") or ""),
        "origin": str(spec.get("origin") or ""),
        "tint": str(spec.get("tint") or "#ffffff"),
        "transfer": bool(spec.get("transfer", False)),
        "statuses": _normalize_statuses(
            spec.get("statuses", spec.get("status"))
        ),
        "sort": _integer(spec.get("sort"), 0),
        "flags": flags,
    }


def _selected_activities(
    selector: Any,
    activities: list[dict[str, Any]],
    *,
    default_to_first: bool,
) -> list[dict[str, Any]]:
    if not activities:
        return []
    if selector in (None, ""):
        return [activities[0]] if default_to_first else []
    if selector == "all":
        return activities
    if isinstance(selector, list):
        result: list[dict[str, Any]] = []
        for item in selector:
            for activity in _selected_activities(
                item,
                activities,
                default_to_first=False,
            ):
                if activity not in result:
                    result.append(activity)
        return result
    if _is_number(selector):
        index = _integer(selector, -1)
        return [activities[index]] if 0 <= index < len(activities) else []
    text = str(selector).casefold().strip()
    return [
        activity
        for activity in activities
        if text
        in {
            str(activity.get("_id") or "").casefold(),
            str(activity.get("name") or "").casefold(),
        }
    ]


def _build_effects(
    mechanics: dict[str, Any],
    activities: list[dict[str, Any]],
    weapon_name: str,
    report: BuildReport,
    existing_effects: list[Any] | None = None,
) -> list[dict[str, Any]]:
    specs = midi_compat.collect_effect_specs(mechanics)
    if not specs:
        return []
    default_duration = (
        mechanics.get("duration")
        if isinstance(mechanics.get("duration"), dict)
        else {}
    )
    result: list[dict[str, Any]] = []
    used_ids: set[str] = {
        str(effect.get("_id"))
        for effect in (existing_effects or [])
        if isinstance(effect, dict) and effect.get("_id")
    }
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict):
            report.warning(
                f"{weapon_name}: эффект #{index + 1} пропущен — "
                "ожидался JSON-объект."
            )
            continue
        raw_effect_id = str(spec.get("_id") or "").strip()
        if raw_effect_id and not re.fullmatch(
            r"[A-Za-z0-9]{16}", raw_effect_id
        ):
            report.warning(
                f"{weapon_name}: некорректный _id эффекта "
                f"«{raw_effect_id}» заменён автоматически."
            )
        effect = _build_effect(spec, index, weapon_name, default_duration)
        if effect["_id"] in used_ids:
            report.warning(
                f"{weapon_name}: повторяющийся _id эффекта "
                f"«{effect['_id']}» заменён автоматически."
            )
            replacement_index = index
            effect["_id"] = _effect_id(replacement_index)
            while effect["_id"] in used_ids:
                replacement_index += 1
                effect["_id"] = _effect_id(replacement_index)
        used_ids.add(effect["_id"])
        selector = spec.get("activity", spec.get("activities"))
        targets = _selected_activities(
            selector,
            activities,
            default_to_first=not effect["transfer"],
        )
        if selector not in (None, "") and not targets:
            report.warning(
                f"{weapon_name}: эффект «{effect['name']}» создан, "
                "но указанная activity не найдена."
            )
        elif not targets and not effect["transfer"]:
            report.warning(
                f"{weapon_name}: эффект «{effect['name']}» создан, "
                "но не привязан к активности."
            )
        reference = {
            "_id": effect["_id"],
            "onSave": bool(spec.get("on_save", False)),
            "level": {
                "min": (
                    _integer(spec.get("level_min"))
                    if spec.get("level_min") not in (None, "")
                    else None
                ),
                "max": (
                    _integer(spec.get("level_max"))
                    if spec.get("level_max") not in (None, "")
                    else None
                ),
            },
        }
        for activity in targets:
            activity["effects"].append(deepcopy(reference))
        result.append(effect)
    return result


def _activity_mechanics(
    parent: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, Any]:
    merged = deepcopy(parent)
    merged.pop("activities", None)
    # На уровне mechanics.uses описываются общие заряды предмета.
    # Собственные использования активности задаются только внутри её spec.
    merged.pop("uses", None)
    for key, value in spec.items():
        if key != "type":
            merged[key] = deepcopy(value)
    return merged


def _has_attack_evidence(mechanics: dict[str, Any]) -> bool:
    activity_specs = mechanics.get("activities")
    if isinstance(activity_specs, list) and activity_specs:
        return False
    save = mechanics.get("save")
    text = str(mechanics.get("text") or "")
    textual_attack = bool(
        re.search(
            r"(?:\[\[/attack|[+-]\s*\d+\s*(?:к\s+попадан|to hit)|"
            r"бросок\s+атаки|attack roll)",
            text,
            re.I,
        )
    )
    return not save or bool(mechanics.get("attack_evidence")) or textual_attack


def _build_activities(
    mechanics: dict[str, Any],
    weapon_name: str,
    report: BuildReport,
) -> list[dict[str, Any]]:
    specs = mechanics.get("activities")
    result: list[dict[str, Any]] = []
    if isinstance(specs, list) and specs:
        for index, spec in enumerate(specs):
            if not isinstance(spec, dict):
                report.warning(
                    f"{weapon_name}: activity #{index + 1} пропущена — "
                    "ожидался JSON-объект."
                )
                continue
            activity_type = str(spec.get("type") or "").casefold()
            if activity_type not in {
                "attack", "save", "damage", "heal", "utility"
            }:
                report.warning(
                    f"{weapon_name}: неизвестный тип activity "
                    f"«{activity_type or 'пусто'}»; элемент #{index + 1} пропущен."
                )
                continue
            activity_data = _activity_mechanics(mechanics, spec)
            if (
                activity_type == "attack"
                and spec.get("include_base") is None
                and mechanics.get("include_base") is None
            ):
                parent_damage = mechanics.get("damage")
                activity_damage = activity_data.get("damage")
                first_parent = (
                    parent_damage[0]
                    if isinstance(parent_damage, list) and parent_damage
                    else None
                )
                first_activity = (
                    activity_damage[0]
                    if isinstance(activity_damage, list) and activity_damage
                    else None
                )
                already_has_attack = any(
                    built.get("type") == "attack" for built in result
                )
                activity_data["include_base"] = bool(
                    not already_has_attack
                    and isinstance(first_parent, dict)
                    and isinstance(first_activity, dict)
                    and _normalize_formula(first_parent.get("formula"))
                    == _normalize_formula(first_activity.get("formula"))
                    and str(first_parent.get("type") or "")
                    == str(first_activity.get("type") or "")
                )
            raw_activity_id = str(spec.get("_id") or "").strip()
            if raw_activity_id and not re.fullmatch(
                r"[A-Za-z0-9]{16}", raw_activity_id
            ):
                report.warning(
                    f"{weapon_name}: некорректный _id activity "
                    f"«{raw_activity_id}» заменён автоматически."
                )
                raw_activity_id = ""
            activity_id = raw_activity_id or _activity_id(index)
            used_ids = {item["_id"] for item in result}
            if activity_id in used_ids:
                report.warning(
                    f"{weapon_name}: повторяющийся _id activity "
                    f"«{activity_id}» заменён автоматически."
                )
                replacement_index = index
                activity_id = _activity_id(replacement_index)
                while activity_id in used_ids:
                    replacement_index += 1
                    activity_id = _activity_id(replacement_index)
            if activity_type == "attack":
                activity = _build_attack_activity(activity_data, activity_id)
            elif activity_type == "save":
                activity = _build_save_activity(activity_data, activity_id)
            elif activity_type == "damage":
                activity = _build_damage_activity(activity_data, activity_id)
            elif activity_type == "heal":
                activity = _build_heal_activity(activity_data, activity_id)
            elif activity_type == "utility":
                activity = _build_utility_activity(activity_data, activity_id)
            else:
                activity = None
            if activity is not None:
                result.append(activity)
            else:
                report.warning(
                    f"{weapon_name}: activity "
                    f"«{spec.get('activity_name') or activity_type}» "
                    "не создана — отсутствуют обязательные механические поля."
                )
        return result

    attack_activity = (
        _build_attack_activity(mechanics, _activity_id(0))
        if _has_attack_evidence(mechanics)
        else None
    )
    if attack_activity is not None:
        result.append(attack_activity)

    save = mechanics.get("save")
    if isinstance(save, dict) and save:
        save_mechanics = deepcopy(mechanics)
        if attack_activity is not None:
            save_damage = save.get("damage")
            save_mechanics["damage"] = (
                deepcopy(save_damage) if isinstance(save_damage, list) else []
            )
        save_activity = _build_save_activity(
            save_mechanics,
            _activity_id(len(result)),
        )
        if save_activity is not None:
            result.append(save_activity)

    activation = mechanics.get("activation")
    activation_type = (
        str(activation.get("type") or "") if isinstance(activation, dict) else ""
    )
    if not result and activation_type in {
        "bonus",
        "reaction",
        "legendary",
        "lair",
        "special",
    }:
        result.append(_build_utility_activity(mechanics, _activity_id(0)))
    return result


def _apply_item_uses(
    system: dict[str, Any],
    mechanics: dict[str, Any],
    report: BuildReport,
    path: str,
) -> None:
    uses_data = mechanics.get("uses")
    if not isinstance(uses_data, dict) or not uses_data:
        return
    uses = _ensure_dict(system, "uses", report, path)
    old = deepcopy(uses)
    if uses_data.get("max") not in (None, ""):
        uses["max"] = str(uses_data["max"])
    uses["spent"] = _integer(uses_data.get("spent"), 0)
    recovery = uses_data.get("recovery")
    if isinstance(recovery, list):
        uses["recovery"] = deepcopy(recovery)
    if uses != old:
        report.change(f"{path}.uses", "configured_uses", old, deepcopy(uses))


def _consume_builder_mechanics(
    weapon: dict[str, Any],
    system: dict[str, Any],
    report: BuildReport,
    path: str,
) -> None:
    for metadata_parent, metadata_path in (
        (weapon, path),
        (system, f"{path}.system"),
    ):
        if "mechanics" in metadata_parent:
            old = metadata_parent.pop("mechanics")
            report.change(
                f"{metadata_path}.mechanics",
                "consumed_builder_metadata",
                old,
                None,
            )

    flags = weapon.get("flags")
    if not isinstance(flags, dict):
        return
    namespace = flags.get("foundry-content-generator")
    if not isinstance(namespace, dict) or "mechanics" not in namespace:
        return
    old = namespace.pop("mechanics")
    report.change(
        f"{path}.flags.foundry-content-generator.mechanics",
        "consumed_builder_metadata",
        old,
        None,
    )


def _audit_existing_activities(
    activities: dict[str, Any],
    weapon_name: str,
    report: BuildReport,
    path: str,
) -> None:
    for key, activity in activities.items():
        if not isinstance(activity, dict):
            report.warning(
                f"{weapon_name}: существующая activity «{key}» "
                "не является объектом."
            )
            continue
        added = midi_compat.normalize_activity(activity)
        if added:
            report.change(
                f"{path}.{key}",
                "added_midi_qol_defaults",
                None,
                deepcopy(added),
            )
        activity_type = str(activity.get("type") or "").casefold()
        if activity_type not in {
            "attack", "save", "damage", "heal", "utility"
        }:
            report.warning(
                f"{weapon_name}: существующая activity «{key}» имеет "
                f"неизвестный тип «{activity_type or 'пусто'}»."
            )
        raw_id = str(activity.get("_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9]{16}", raw_id):
            report.warning(
                f"{weapon_name}: существующая activity «{key}» имеет "
                f"некорректный _id «{raw_id or 'пусто'}»."
            )
        elif raw_id != str(key):
            report.warning(
                f"{weapon_name}: ключ activity «{key}» не совпадает "
                f"с её _id «{raw_id}»."
            )


def _normalize_weapon(
    weapon: dict[str, Any],
    report: BuildReport,
    path: str,
    actor_system: dict[str, Any] | None = None,
) -> None:
    name = weapon.get("name")
    if not isinstance(name, str) or not name.strip():
        old = name
        weapon["name"] = "Безымянное оружие"
        report.change(f"{path}.name", "filled_required_name", old, weapon["name"])
    else:
        weapon["name"] = name.strip()

    _default(
        weapon,
        "img",
        "icons/weapons/swords/greatsword-crossguard-steel.webp",
        report,
        path,
    )
    _default(weapon, "folder", None, report, path)
    _default(weapon, "flags", {}, report, path)
    _default(
        weapon,
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

    system = _ensure_dict(weapon, "system", report, path)
    weapon_effects = _ensure_list(weapon, "effects", report, path)

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

    source = _ensure_dict(system, "source", report, f"{path}.system")
    _default(source, "custom", "", report, f"{path}.system.source")
    _default(source, "book", "", report, f"{path}.system.source")
    _default(source, "page", "", report, f"{path}.system.source")
    _default(source, "license", "", report, f"{path}.system.source")
    _default(source, "rules", "2024", report, f"{path}.system.source")
    _default(source, "revision", 1, report, f"{path}.system.source")

    _default(system, "quantity", 1, report, f"{path}.system")
    weight = _ensure_dict(system, "weight", report, f"{path}.system")
    _default(weight, "value", 0, report, f"{path}.system.weight")
    _default(weight, "units", "lb", report, f"{path}.system.weight")
    price = _ensure_dict(system, "price", report, f"{path}.system")
    _default(price, "value", 0, report, f"{path}.system.price")
    _default(price, "denomination", "gp", report, f"{path}.system.price")
    uses = _ensure_dict(system, "uses", report, f"{path}.system")
    _default(uses, "max", "", report, f"{path}.system.uses")
    _default(uses, "spent", 0, report, f"{path}.system.uses")
    _ensure_list(uses, "recovery", report, f"{path}.system.uses")

    _default(system, "identified", True, report, f"{path}.system")
    _default(system, "equipped", False, report, f"{path}.system")
    _default(system, "rarity", "", report, f"{path}.system")
    _default(system, "attunement", "", report, f"{path}.system")
    _default(system, "attuned", False, report, f"{path}.system")
    _default(system, "properties", [], report, f"{path}.system")
    _default(system, "proficient", None, report, f"{path}.system")
    _default(system, "identifier", _slug(weapon["name"]), report, f"{path}.system")
    _default(system, "mastery", "", report, f"{path}.system")
    _default(system, "ammunition", {}, report, f"{path}.system")

    try:
        enhancement_policy.apply_item_policy(weapon, report, path)
    except enhancement_policy.EnhancementPolicyError as error:
        raise WeaponBuilderError(str(error)) from error

    weapon_type = _ensure_dict(system, "type", report, f"{path}.system")
    default_type = "natural" if actor_system is not None else "simpleM"
    _default(weapon_type, "value", default_type, report, f"{path}.system.type")
    _default(weapon_type, "baseItem", "", report, f"{path}.system.type")

    range_data = _ensure_dict(system, "range", report, f"{path}.system")
    _default(range_data, "value", None, report, f"{path}.system.range")
    _default(range_data, "long", None, report, f"{path}.system.range")
    _default(range_data, "reach", None, report, f"{path}.system.range")
    _default(range_data, "units", "ft", report, f"{path}.system.range")

    activities = system.get("activities")
    if isinstance(activities, list):
        converted = {}
        for index, activity in enumerate(activities):
            if isinstance(activity, dict):
                raw_activity_id = str(activity.get("_id") or "").strip()
                activity_id = (
                    raw_activity_id
                    if re.fullmatch(r"[A-Za-z0-9]{16}", raw_activity_id)
                    else _activity_id(index)
                )
                activity["_id"] = activity_id
                converted[activity_id] = activity
        system["activities"] = converted
        report.change(
            f"{path}.system.activities",
            "converted_activity_array",
            activities,
            deepcopy(converted),
        )
        activities = converted
    elif not isinstance(activities, dict):
        old = activities
        activities = {}
        system["activities"] = activities
        report.change(
            f"{path}.system.activities",
            "created_object",
            old,
            deepcopy(activities),
        )

    before = len(activities)
    if before:
        _audit_existing_activities(
            activities,
            weapon["name"],
            report,
            f"{path}.system.activities",
        )
        _normalize_damage_container(system, report, f"{path}.system")
        report.weapons.append(
            WeaponResult(
                weapon["name"],
                "preserved",
                before,
                before,
                "Существующие activities сохранены без замены.",
            )
        )
        return

    mechanics = _merged_mechanics(weapon, actor_system)
    mechanics["_item_magical_bonus"] = _number(
        system.get("magicalBonus"), 0
    )
    _apply_item_uses(system, mechanics, report, f"{path}.system")
    _consume_builder_mechanics(weapon, system, report, path)

    built_activities = _build_activities(
        mechanics,
        weapon["name"],
        report,
    )
    built_effects = _build_effects(
        mechanics,
        built_activities,
        weapon["name"],
        report,
        weapon_effects,
    )
    for effect in built_effects:
        weapon_effects.append(effect)
        report.change(
            f"{path}.effects[{len(weapon_effects) - 1}]",
            "created_active_effect",
            None,
            deepcopy(effect),
        )
    if not built_activities:
        _normalize_damage_container(system, report, f"{path}.system")
        report.weapons.append(
            WeaponResult(
                weapon["name"],
                "created_effects" if built_effects else "manual",
                0,
                0,
                (
                    f"Созданы Active Effects: {len(built_effects)}."
                    if built_effects
                    else "Не удалось безопасно определить атаку и урон."
                ),
            )
        )
        if not built_effects:
            report.warning(
                f"{weapon['name']}: не создана активность атаки — "
                "недостаточно данных."
            )
        return

    damage = mechanics.get("damage")
    if isinstance(damage, list) and damage:
        _write_base_damage(
            system,
            damage[0],
            report,
            f"{path}.system",
        )
    range_result = mechanics["range"]
    old_range = deepcopy(range_data)
    for key in ("value", "long", "reach", "units"):
        if range_result.get(key) not in (None, ""):
            range_data[key] = range_result[key]
    if old_range != range_data:
        report.change(
            f"{path}.system.range",
            "configured_range",
            old_range,
            deepcopy(range_data),
        )

    for activity in built_activities:
        activities[activity["_id"]] = activity
        report.change(
            f"{path}.system.activities.{activity['_id']}",
            f"created_{activity['type']}_activity",
            None,
            deepcopy(activity),
        )

    activity_types = [activity["type"] for activity in built_activities]
    message = "Созданы activities: " + ", ".join(activity_types) + "."
    if built_effects:
        message += f" Active Effects: {len(built_effects)}."
    report.weapons.append(
        WeaponResult(
            weapon["name"],
            "created_activities",
            0,
            len(built_activities),
            message,
        )
    )


def normalize_document(
    source: dict[str, Any],
    source_name: str = "",
) -> tuple[dict[str, Any], BuildReport, str]:
    """Нормализует актёра или отдельное оружие."""
    if not isinstance(source, dict):
        raise WeaponBuilderError("Корень JSON должен быть объектом.")

    document = deepcopy(source)
    report = BuildReport(source=source_name)
    document_type = document.get("type")

    if document_type == "weapon":
        _normalize_weapon(document, report, "$")
        return document, report, "weapon"

    items = document.get("items")
    if not isinstance(items, list):
        raise WeaponBuilderError(
            "Ожидался type='weapon' либо JSON актёра с массивом items."
        )

    actor_system = document.get("system")
    actor_system = actor_system if isinstance(actor_system, dict) else None
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("type") == "weapon":
            _normalize_weapon(
                item,
                report,
                f"$.items[{index}]",
                actor_system=actor_system,
            )
    return document, report, "actor"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except FileNotFoundError as error:
        raise WeaponBuilderError(f"Файл не найден: {path}") from error
    except json.JSONDecodeError as error:
        raise WeaponBuilderError(
            f"Ошибка JSON в {path}, строка {error.lineno}, столбец {error.colno}: "
            f"{error.msg}"
        ) from error
    except OSError as error:
        raise WeaponBuilderError(f"Не удалось прочитать {path}: {error}") from error
    if not isinstance(data, dict):
        raise WeaponBuilderError("Корень JSON должен быть объектом.")
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
        raise WeaponBuilderError(f"Не удалось записать {path}: {error}") from error


def _default_input() -> Path:
    actor_output_directory = Path("output/actors")
    if actor_output_directory.is_dir():
        actor_outputs = [
            path
            for path in actor_output_directory.glob("*_foundry.json")
            if path.is_file()
        ]
        if not actor_outputs:
            actor_outputs = [
                path
                for path in actor_output_directory.glob("*.json")
                if path.is_file()
            ]
        if actor_outputs:
            return max(
                actor_outputs,
                key=lambda path: (path.stat().st_mtime_ns, path.name.casefold()),
            )

    candidates = (
        Path("output/actors/npc_foundry.json"),
        Path("input/npc.json"),
        Path("input/weapon.json"),
        Path("weapon.json"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _default_output(document: dict[str, Any], kind: str) -> Path:
    name = _safe_filename(str(document.get("name") or "Безымянный"))
    if kind == "actor":
        return Path("output/actors") / f"{name}_foundry.json"
    return Path("output/weapons") / f"{name}_foundry.json"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Нормализует оружие для Foundry VTT 13.351 / D&D5e 5.3.3."
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=None,
        help="JSON актёра или отдельного оружия.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Путь итогового JSON.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("logs/weapon_builder_report.json"),
        help="Путь к JSON-отчёту.",
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
        document, report, kind = normalize_document(
            source,
            source_name=str(source_path),
        )
        if kind == "weapon":
            compatibility = midi_compat.audit_document(document)
            if compatibility["errors"]:
                raise WeaponBuilderError(
                    "Проверка Midi-QOL/DAE не пройдена: "
                    + "; ".join(compatibility["errors"][:5])
                )
            for warning in compatibility["warnings"]:
                report.warning(f"Midi-QOL/DAE: {warning}")
        output_path = args.output or _default_output(document, kind)
        report.output = str(output_path)
        _atomic_json_write(output_path, document, args.indent)
        _atomic_json_write(args.report, asdict(report), args.indent)
    except WeaponBuilderError as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return 1

    counts: dict[str, int] = {}
    for weapon in report.weapons:
        counts[weapon.status] = counts.get(weapon.status, 0) + 1
    print(f"Готово: {document.get('name', 'Безымянный')}")
    print(f"Источник: {source_path}")
    print(f"JSON: {output_path}")
    print(f"Отчёт: {args.report}")
    if counts:
        summary = ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
        print(f"Оружие: {summary}")
    if report.warnings:
        print(f"Предупреждений: {len(report.warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
