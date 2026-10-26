#!/usr/bin/env python3
"""
Нормализация особенностей Foundry VTT 13.351 / D&D5e 5.3.3.

Билдер принимает:
  * полный JSON актёра и обрабатывает все вложенные предметы type="feat";
  * отдельный JSON особенности type="feat".

Он сохраняет уже рабочие activities, создаёт attack/save/damage/heal/utility,
Active Effects и расходы ресурсов, переносит механику старого формата и
консервативно извлекает из русского/английского описания спасбросок, урон,
дальность, конус, длительность, перезарядку и число использований.

Запуск:
    python feat_builder.py output/actors/Мрачный Жнец_foundry.json
    python feat_builder.py input/feat.json
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


WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
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

CONDITION_PATTERNS = (
    (r"(?:ис|на)пуган|frightened", "frightened"),
    (r"парализован|paralyzed", "paralyzed"),
    (r"ослепл[её]н|blinded", "blinded"),
    (r"очарован|charmed", "charmed"),
    (r"оглуш[её]н|stunned", "stunned"),
    (r"отравлен|poisoned", "poisoned"),
    (r"опутан|restrained", "restrained"),
    (r"сбит\w*\s+с\s+ног|prone", "prone"),
    (r"схвачен|grappled", "grappled"),
    (r"недееспособ|incapacitated", "incapacitated"),
    (r"без\s+сознания|unconscious", "unconscious"),
    (r"оглох|глух|deafened", "deafened"),
    (r"невидим|invisible", "invisible"),
    (r"истощени|exhaustion", "exhaustion"),
)

ACTIVATION_TYPES = {
    "action",
    "bonus",
    "reaction",
    "legendary",
    "lair",
    "special",
    "none",
}

ACTIVITY_TYPES = {"attack", "save", "damage", "heal", "utility"}

EFFECT_MODE_ALIASES = {
    "custom": 0,
    "особый": 0,
    "multiply": 1,
    "умножить": 1,
    "add": 2,
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
    "ослеплён": "blinded",
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
    "оглушён": "stunned",
    "unconscious": "unconscious",
    "без сознания": "unconscious",
}


class FeatBuilderError(Exception):
    """Ошибка, из-за которой безопасная обработка невозможна."""


@dataclass
class Change:
    path: str
    action: str
    old: Any = None
    new: Any = None


@dataclass
class FeatResult:
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
    feats: list[FeatResult] = field(default_factory=list)

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


def _formula(value: Any) -> str:
    """Возвращает число или формулу Foundry как непустую строку."""
    if value is None or isinstance(value, bool):
        return ""
    if _is_number(value):
        return str(value)
    return str(value).strip()


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
    return text or "osobennost"


def _safe_filename(value: str) -> str:
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    filename = re.sub(r"\s+", " ", filename)
    if not filename:
        filename = "Безымянная особенность"
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


def _formula_parts(formula: str, damage_type: str) -> dict[str, Any]:
    compact = re.sub(r"\s+", "", formula.casefold()).replace("к", "d")
    match = re.fullmatch(r"(\d+)d(\d+)(?:([+-])(\d+))?", compact)
    if not match:
        return {
            "number": None,
            "denomination": 0,
            "bonus": "",
            "types": [damage_type] if damage_type else [],
            "custom": {"enabled": True, "formula": formula},
            "scaling": {"mode": "whole", "number": None, "formula": ""},
        }
    number, denomination, sign, bonus = match.groups()
    bonus_text = f"{sign}{bonus}" if sign and bonus else ""
    return {
        "number": int(number),
        "denomination": int(denomination),
        "bonus": bonus_text,
        "types": [damage_type] if damage_type else [],
        "custom": {"enabled": False, "formula": ""},
        "scaling": {"mode": "whole", "number": None, "formula": ""},
    }


def _healing_parts(formula: str, healing_type: str) -> dict[str, Any]:
    compact = re.sub(r"\s+", "", formula.casefold()).replace("к", "d")
    match = re.fullmatch(
        r"(\d+)d(\d+)(?:([+-])(\d+)|\+(@[a-z0-9_.]+))?",
        compact,
    )
    if not match:
        return {
            "number": None,
            "denomination": 0,
            "bonus": "",
            "types": [healing_type],
            "custom": {"enabled": True, "formula": formula},
            "scaling": {"mode": "whole", "number": None, "formula": ""},
        }
    number, denomination, sign, numeric_bonus, reference_bonus = match.groups()
    if reference_bonus:
        bonus_text = reference_bonus
    elif sign and numeric_bonus:
        bonus_text = f"{sign}{numeric_bonus}"
    else:
        bonus_text = ""
    return {
        "number": int(number),
        "denomination": int(denomination),
        "bonus": bonus_text,
        "types": [healing_type],
        "custom": {"enabled": False, "formula": ""},
        "scaling": {"mode": "whole", "number": None, "formula": ""},
    }


def _base_activity(activity_id: str, activity_type: str) -> dict[str, Any]:
    activity: dict[str, Any] = {
        "_id": activity_id,
        "type": activity_type,
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
            "units": "self",
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
                "units": "any",
                "stationary": False,
            },
            "affects": {
                "count": "",
                "type": "creature",
                "choice": False,
                "special": "",
            },
            "prompt": True,
            "override": False,
        },
        "uses": {"spent": 0, "max": "", "recovery": []},
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
        "otherActivityId": "none",
        "otherActivityAsParentType": True,
        "friendlySave": "default",
    }
    if activity_type == "attack":
        activity["attack"] = {
            "ability": "",
            "bonus": "",
            "critical": {"threshold": None},
            "flat": False,
            "type": {"value": "melee", "classification": "weapon"},
        }
        activity["damage"] = {
            "critical": {"bonus": ""},
            "includeBase": True,
            "parts": [],
        }
    elif activity_type == "save":
        activity["damage"] = {
            "onSave": "none",
            "parts": [],
            "critical": {"allow": False},
        }
        activity["save"] = {
            "ability": [],
            "dc": {"calculation": "", "formula": ""},
        }
    elif activity_type == "damage":
        activity["damage"] = {
            "critical": {"allow": False},
            "parts": [],
        }
    elif activity_type == "heal":
        activity["range"].pop("value", None)
        activity["target"]["affects"]["type"] = "self"
        activity["healing"] = _healing_parts("", "healing")
        activity["healing"]["custom"] = {"enabled": False, "formula": ""}
    elif activity_type == "utility":
        activity["range"].pop("value", None)
        activity["target"]["affects"]["type"] = ""
        activity["roll"] = {
            "formula": "",
            "name": "",
            "prompt": False,
            "visible": False,
        }
    midi_compat.normalize_activity(activity)
    return activity


def _extract_explicit_mechanics(feat: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        feat.get("mechanics"),
        (feat.get("system") or {}).get("mechanics")
        if isinstance(feat.get("system"), dict)
        else None,
    ]
    flags = feat.get("flags")
    if isinstance(flags, dict):
        namespace = flags.get("foundry-content-generator")
        if isinstance(namespace, dict):
            candidates.append(namespace.get("mechanics"))
    for candidate in candidates:
        if isinstance(candidate, dict):
            return deepcopy(candidate)
    return {}


def _was_processed_without_activity(feat: dict[str, Any]) -> bool:
    flags = feat.get("flags")
    if not isinstance(flags, dict):
        return False
    namespace = flags.get("foundry-content-generator")
    if not isinstance(namespace, dict):
        return False
    marker = namespace.get("feat_builder")
    return isinstance(marker, dict) and bool(marker.get("processed"))


def _mark_processed_without_activity(feat: dict[str, Any]) -> None:
    flags = feat.setdefault("flags", {})
    if not isinstance(flags, dict):
        return
    namespace = flags.setdefault("foundry-content-generator", {})
    if not isinstance(namespace, dict):
        return
    namespace["feat_builder"] = {
        "processed": True,
        "format": 1,
    }


def _consume_builder_mechanics(
    feat: dict[str, Any],
    system: dict[str, Any],
    report: BuildReport,
    path: str,
) -> None:
    for metadata_parent, metadata_path in (
        (feat, path),
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

    flags = feat.get("flags")
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


def _extract_save(text: str, system: dict[str, Any]) -> dict[str, Any]:
    legacy = system.get("save")
    if isinstance(legacy, dict):
        ability = _normalize_ability(legacy.get("ability"))
        dc = _integer(legacy.get("dc") or legacy.get("value"), 0)
        if ability and dc:
            return {"ability": ability, "dc": dc}

    ability_ru = r"(силы|ловкости|телосложения|интеллекта|мудрости|харизмы)"
    ability_en = (
        r"(strength|dexterity|constitution|intelligence|wisdom|charisma)"
    )
    patterns = (
        (rf"спасброс\w*\s+{ability_ru}\s*(?:сл|dc)\s*(\d+)", "ability_dc"),
        (rf"спасброс\w*\s+(?:сл|dc)\s*(\d+)\s+{ability_ru}", "dc_ability"),
        (rf"(?:сл|dc)\s*(\d+)\s+спасброс\w*\s+{ability_ru}", "dc_ability"),
        (rf"(?:dc|сл)\s*(\d+)\s*{ability_en}", "dc_ability"),
        (
            rf"{ability_en}\s+saving throw(?:\s*,?\s*(?:dc)?)?\s*(\d+)",
            "ability_dc",
        ),
        (
            rf"(?:dc)\s*(\d+)\s*{ability_en}\s+saving throw",
            "dc_ability",
        ),
    )
    normalized = text.casefold().replace("ё", "е")
    for pattern, order in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if not match:
            continue
        first, second = match.groups()
        if order == "dc_ability":
            dc, ability_text = first, second
        else:
            ability_text, dc = first, second
        ability = _normalize_ability(ability_text)
        if ability:
            return {"ability": ability, "dc": int(dc)}
    return {}


def _damage_type_near(text: str, start: int, end: int) -> str:
    window_start = max(0, start - 60)
    window_end = min(len(text), end + 90)
    window = text[window_start:window_end].casefold()
    formula_start = start - window_start
    formula_end = end - window_start
    candidates: list[tuple[int, str]] = []
    for pattern, damage_type in DAMAGE_TYPE_PATTERNS:
        for match in re.finditer(pattern, window):
            if match.end() <= formula_start:
                distance = formula_start - match.end()
            elif match.start() >= formula_end:
                distance = match.start() - formula_end
            else:
                distance = 0
            candidates.append((distance, damage_type))
    return min(candidates, default=(0, ""))[1]


def _extract_damage(text: str, system: dict[str, Any]) -> list[dict[str, str]]:
    legacy = system.get("damage")
    if isinstance(legacy, dict) and isinstance(legacy.get("parts"), list):
        result: list[dict[str, str]] = []
        for part in legacy["parts"]:
            if isinstance(part, (list, tuple)) and part:
                result.append(
                    {
                        "formula": str(part[0]),
                        "type": str(part[1]) if len(part) > 1 else "",
                    }
                )
            elif isinstance(part, dict):
                formula = part.get("formula")
                if formula:
                    result.append(
                        {"formula": str(formula), "type": str(part.get("type") or "")}
                    )
        if result:
            return result

    result = []
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
        damage_type = _damage_type_near(text, match.start(), match.end())
        local_context = text[
            max(0, match.start() - 50) : min(len(text), match.end() + 80)
        ]
        if not damage_type and not re.search(
            r"урон|поврежден|damage", local_context, re.IGNORECASE
        ):
            continue
        key = (formula, damage_type)
        if key not in seen:
            seen.add(key)
            result.append({"formula": formula, "type": damage_type})
    return result


def _extract_healing(text: str, system: dict[str, Any]) -> dict[str, str]:
    legacy = system.get("healing")
    if isinstance(legacy, dict):
        custom = legacy.get("custom")
        if isinstance(custom, dict) and custom.get("enabled") and custom.get("formula"):
            formula = str(custom["formula"]).strip()
        else:
            number = legacy.get("number")
            denomination = legacy.get("denomination")
            if _is_number(number) and _is_number(denomination):
                formula = f"{int(number)}d{int(denomination)}"
                bonus = str(legacy.get("bonus") or "").strip()
                if bonus:
                    formula += bonus if bonus.startswith(("+", "-", "@")) else f"+{bonus}"
            else:
                formula = ""
        types = legacy.get("types")
        healing_type = str(types[0]) if isinstance(types, list) and types else "healing"
        if formula:
            return {"formula": formula, "type": healing_type}

    normalized = text.casefold().replace("ё", "е")
    healing_words = r"(?:восстанов\w*|исцел\w*|леч\w*|regain\w*|restore\w*|heal\w*)"
    hp_words = r"(?:пз|хит\w*|hit points?)"
    formula_pattern = r"(\d+\s*[dк]\s*\d+(?:\s*[+-]\s*\d+)?|\d+)"
    patterns = (
        rf"{healing_words}[^.;]{{0,100}}?{formula_pattern}\s*{hp_words}",
        rf"{healing_words}[^.;]{{0,70}}?{hp_words}[^.;]{{0,45}}?{formula_pattern}",
    )
    formula = ""
    match_end = 0
    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            formula = re.sub(r"\s+", "", match.group(1)).replace("к", "d")
            match_end = match.end()
            break
    if not formula:
        return {}

    nearby = normalized[max(0, match_end - 40) : min(len(normalized), match_end + 100)]
    bonus_map = (
        (r"(?:уровень\s+воина|fighter level)", "@classes.fighter.levels"),
        (r"(?:модификатор\w*\s+телослож|constitution modifier)", "@abilities.con.mod"),
        (r"(?:модификатор\w*\s+мудрост|wisdom modifier)", "@abilities.wis.mod"),
        (r"(?:модификатор\w*\s+харизм|charisma modifier)", "@abilities.cha.mod"),
    )
    if "d" in formula and not re.search(r"[+-]\d+$", formula):
        for pattern, reference in bonus_map:
            if re.search(pattern, nearby):
                formula += f"+{reference}"
                break
    healing_type = (
        "temphp"
        if re.search(r"временн\w*\s+(?:пз|хит)|temporary hit points?", normalized)
        else "healing"
    )
    return {"formula": formula, "type": healing_type}


def _extract_recovery(name: str, text: str) -> dict[str, Any]:
    combined = f"{name} {text}".casefold().replace("ё", "е")
    recharge = re.search(
        r"(?:перезарядк\w*|recharge)\s*(\d+)(?:\s*[–—-]\s*(\d+))?",
        combined,
    )
    if recharge:
        minimum = int(recharge.group(1))
        return {
            "max": 1,
            "recovery": [
                {"period": "recharge", "formula": str(minimum), "type": "recoverAll"}
            ],
        }

    daily = re.search(
        r"(?:\(|\b)(\d+)\s*/\s*(?:день|дня|day)(?:\)|\b)",
        combined,
    )
    if daily:
        maximum = int(daily.group(1))
        return {
            "max": maximum,
            "recovery": [{"period": "day", "formula": "", "type": "recoverAll"}],
        }

    rest_patterns = (
        (
            r"(?:\(|\b)(\d+)\s*/\s*(?:коротк\w*\s+отдых|short rest)(?:\)|\b)",
            "sr",
        ),
        (
            r"(?:\(|\b)(\d+)\s*/\s*(?:продолжительн\w*|длинн\w*)\s+"
            r"отдых(?:\)|\b)|(?:\(|\b)(\d+)\s*/\s*long rest(?:\)|\b)",
            "lr",
        ),
    )
    for pattern, period in rest_patterns:
        match = re.search(pattern, combined)
        if match:
            maximum = int(next(group for group in match.groups() if group))
            return {
                "max": maximum,
                "recovery": [
                    {"period": period, "formula": "", "type": "recoverAll"}
                ],
            }

    once_per = (
        (r"(?:один раз|once)\s+(?:за|per)\s+(?:коротк\w*\s+отдых|short rest)", "sr"),
        (
            r"(?:один раз|once)\s+(?:за|per)\s+"
            r"(?:(?:продолжительн\w*|длинн\w*)\s+отдых|long rest)",
            "lr",
        ),
        (r"(?:один раз|once)\s+(?:в|per)\s+(?:день|day)", "day"),
    )
    for pattern, period in once_per:
        if re.search(pattern, combined):
            return {
                "max": 1,
                "recovery": [
                    {"period": period, "formula": "", "type": "recoverAll"}
                ],
            }
    if (
        re.search(r"(?:коротк\w*\s+или\s+(?:длинн|продолжительн)\w*\s+отдых|short or long rest)", combined)
        and re.search(r"(?:снова|again|before .* use)", combined)
    ):
        return {
            "max": 1,
            "recovery": [{"period": "sr", "formula": "", "type": "recoverAll"}],
        }
    return {}


def _extract_activation(name: str, text: str) -> dict[str, Any]:
    combined = f"{name} {text}".casefold().replace("ё", "е")
    if re.search(
        r"(?:легендарн\w*\s+(?:стойкост|устойчивост|сопротивлен)|"
        r"(?:стойкост|устойчивост|сопротивлен)\w*\s+легендарн\w*|"
        r"legendary resistance)",
        combined,
    ):
        return {"type": "special", "value": None}
    if "действие логова" in combined or "lair action" in combined:
        return {"type": "lair", "value": 1}
    legendary = re.search(
        r"(?:легендарн\w*\s+действ\w*|legendary action).*?\(?\s*(\d+)\s+действ",
        combined,
    )
    if legendary:
        return {"type": "legendary", "value": int(legendary.group(1))}
    if "легендарное действие" in combined or "legendary action" in combined:
        return {"type": "legendary", "value": 1}
    if "бонусн" in combined or "bonus action" in combined:
        return {"type": "bonus", "value": 1}
    if "реакци" in combined or "reaction" in combined:
        return {"type": "reaction", "value": 1}
    if re.search(r"парирован|парир|parry|parrying", combined):
        return {"type": "reaction", "value": 1}
    if (
        "в начале своего хода" in combined
        or "в конце своего хода" in combined
        or "at the start of its turn" in combined
        or "at the end of its turn" in combined
    ):
        return {"type": "special", "value": None}
    return {"type": "action", "value": 1}


def _extract_duration(text: str) -> dict[str, Any]:
    normalized = text.casefold().replace("ё", "е")
    patterns = (
        (r"(\d+)\s*минут", "minute"),
        (r"(\d+)\s*(?:раунд|round)", "round"),
        (r"(\d+)\s*(?:час|hour)", "hour"),
    )
    for pattern, units in patterns:
        match = re.search(pattern, normalized)
        if match:
            return {"value": match.group(1), "units": units}
    if "до конца следующего хода" in normalized:
        return {"value": "1", "units": "round"}
    if (
        "до начала следующего хода" in normalized
        or "until the start of the next turn" in normalized
        or "until the end of the next turn" in normalized
    ):
        return {"value": "1", "units": "round"}
    return {}


def _extract_range_and_target(text: str) -> dict[str, Any]:
    normalized = text.casefold().replace("ё", "е")
    result: dict[str, Any] = {
        "range": {"value": "", "units": "self"},
        "template": {},
        "affects": {"count": "", "type": "creature", "special": ""},
    }

    cone_patterns = (
        r"конус\w*\s+(\d+)\s*(?:фут|ft)",
        r"(\d+)\s*[- ]?футов\w*\s+конус",
        r"(\d+)\s*[- ]?foot\s+cone",
    )
    for pattern in cone_patterns:
        match = re.search(pattern, normalized)
        if match:
            result["template"] = {
                "type": "cone",
                "size": match.group(1),
                "units": "ft",
            }
            return result

    line = re.search(
        r"(?:лини\w*|line)(?:\s+(?:длиной|длиною|long))?\s+"
        r"(\d+)\s*(?:фут|feet|foot|ft)"
        r"(?:[^.]{0,60}?(?:шириной|wide)\s+(\d+)\s*(?:фут|feet|foot|ft))?",
        normalized,
    )
    if line:
        result["template"] = {
            "type": "line",
            "size": line.group(1),
            "width": line.group(2) or "",
            "units": "ft",
        }
        return result

    radius = re.search(
        r"(?:в\s+радиусе|радиус\w*|radius(?:\s+of)?)\s+"
        r"(\d+)\s*(?:фут|feet|foot|ft)",
        normalized,
    )
    if radius:
        result["template"] = {
            "type": "radius",
            "size": radius.group(1),
            "units": "ft",
        }
        return result

    area_patterns = (
        (
            r"(?:(?:куб\w*|cube)(?:\s+(?:со стороной|side length of))?\s+"
            r"(?P<size>\d+)\s*(?:фут|feet|foot|ft)|"
            r"(?P<size_reverse>\d+)\s*[- ]?(?:футов\w*|feet|foot|ft)\s+"
            r"(?:куб\w*|cube))",
            "cube",
        ),
        (
            r"(?:(?:сфер\w*|sphere)(?:\s+(?:радиусом|radius of))?\s+"
            r"(?P<size>\d+)\s*(?:фут|feet|foot|ft)|"
            r"(?P<size_reverse>\d+)\s*[- ]?(?:футов\w*|feet|foot|ft)\s+"
            r"(?:сфер\w*|sphere))",
            "sphere",
        ),
        (
            r"(?:(?:цилиндр\w*|cylinder)(?:\s+(?:радиусом|radius of))?\s+"
            r"(?P<size>\d+)\s*(?:фут|feet|foot|ft)|"
            r"(?P<size_reverse>\d+)\s*[- ]?(?:футов\w*|feet|foot|ft)\s+"
            r"(?:цилиндр\w*|cylinder))",
            "cylinder",
        ),
    )
    for pattern, template_type in area_patterns:
        match = re.search(pattern, normalized)
        if match:
            result["template"] = {
                "type": template_type,
                "size": match.group("size") or match.group("size_reverse"),
                "units": "ft",
            }
            return result

    distance = re.search(
        r"(?:в пределах|на расстояни\w*(?: до)?|дальност\w*(?: до)?|"
        r"within|range(?: of)?)\s+"
        r"(\d+)\s*(?:фут|feet|foot|ft)",
        normalized,
    )
    if distance:
        result["range"] = {"value": distance.group(1), "units": "ft"}

    if re.search(r"(?:одно|одного|one)\s+существ", normalized):
        result["affects"]["count"] = "1"
    elif re.search(r"(?:все|кажд\w*|all|each)\s+существ", normalized):
        result["affects"]["special"] = "Все подходящие существа"
    return result


def _on_save(text: str) -> str:
    normalized = text.casefold().replace("ё", "е")
    half_damage_patterns = (
        r"(?:при успехе|успех)[^.]{0,100}(?:половин|вдвое меньше)",
        r"(?:половин|вдвое меньше)[^.]{0,100}(?:при успехе|успешн)",
        r"(?:successful save|on a success)[^.]{0,100}(?:half as much|half damage)",
        r"(?:half as much|half damage)[^.]{0,100}(?:successful save|on a success)",
    )
    if any(re.search(pattern, normalized) for pattern in half_damage_patterns):
        return "half"
    if "без урона" in normalized or "no damage" in normalized:
        return "none"
    return "none"


def _detected_conditions(text: str) -> list[str]:
    normalized = text.casefold().replace("ё", "е")
    return [
        condition
        for pattern, condition in CONDITION_PATTERNS
        if re.search(pattern, normalized)
    ]


def _merged_mechanics(feat: dict[str, Any]) -> dict[str, Any]:
    system = feat.get("system")
    if not isinstance(system, dict):
        system = {}
    name = str(feat.get("name") or "")
    text = _plain_text(system.get("description"))
    explicit = _extract_explicit_mechanics(feat)

    attack = explicit.get("attack")
    if not isinstance(attack, dict):
        attack = {}
    else:
        attack = {
            "ability": str(attack.get("ability") or ""),
            "bonus": str(attack.get("bonus") or ""),
            "flat": bool(attack.get("flat", False)),
            "type": str(attack.get("type") or "melee"),
            "classification": str(
                attack.get("classification") or "weapon"
            ),
        }

    save = explicit.get("save")
    if not isinstance(save, dict):
        save = _extract_save(text, system)
    else:
        dc = save.get("dc")
        dc_formula = _formula(
            save.get("dc_formula", save.get("formula"))
        )
        save = {
            "ability": _normalize_ability(save.get("ability")),
            "dc": deepcopy(dc),
            "dc_formula": dc_formula,
            "calculation": str(save.get("calculation") or "").strip(),
        }

    damage = explicit.get("damage")
    if not isinstance(damage, list):
        damage = _extract_damage(text, system)
    normalized_damage = []
    for part in damage:
        if not isinstance(part, dict):
            continue
        formula = str(part.get("formula") or "")
        if formula:
            normalized_damage.append(
                {"formula": formula, "type": str(part.get("type") or "")}
            )

    healing = explicit.get("healing")
    if isinstance(healing, str):
        healing = {"formula": healing, "type": "healing"}
    elif not isinstance(healing, dict):
        healing = _extract_healing(text, system)
    else:
        healing = {
            "formula": str(healing.get("formula") or healing.get("value") or ""),
            "type": str(healing.get("type") or "healing"),
        }

    uses = explicit.get("uses")
    if not isinstance(uses, dict):
        current_uses = system.get("uses")
        if (
            isinstance(current_uses, dict)
            and (
                current_uses.get("max") not in (None, "", 0, "0")
                or current_uses.get("recovery")
            )
        ):
            uses = deepcopy(current_uses)
        else:
            uses = _extract_recovery(name, text)

    activation = explicit.get("activation")
    if not isinstance(activation, dict):
        legacy_activation = system.get("activation")
        if isinstance(legacy_activation, dict):
            activation = {
                "type": legacy_activation.get("type") or "action",
                "value": legacy_activation.get("value")
                or legacy_activation.get("cost")
                or 1,
            }
        else:
            activation = _extract_activation(name, text)

    duration = explicit.get("duration")
    if not isinstance(duration, dict):
        duration = _extract_duration(text)

    targeting = _extract_range_and_target(text)
    explicit_targeting = explicit.get("targeting")
    if isinstance(explicit_targeting, dict):
        if isinstance(explicit_targeting.get("range"), dict):
            targeting["range"].update(explicit_targeting["range"])
        if isinstance(explicit_targeting.get("template"), dict):
            targeting["template"].update(explicit_targeting["template"])
        if isinstance(explicit_targeting.get("affects"), dict):
            explicit_affects = explicit_targeting["affects"]
            targeting["affects"].update(explicit_affects)
            # An explicitly described target block must not inherit a
            # free-form ``special`` value guessed from the prose.  Foundry
            # treats a non-empty special target as a separate targeting mode,
            # which prevents Midi-QOL from reliably auto-targeting templates.
            if "special" not in explicit_affects:
                targeting["affects"]["special"] = ""
        if "prompt" in explicit_targeting:
            targeting["prompt"] = bool(explicit_targeting["prompt"])
    explicit_range = explicit.get("range")
    if isinstance(explicit_range, dict):
        targeting["range"].update(explicit_range)
    explicit_target = explicit.get("target")
    if isinstance(explicit_target, dict):
        if isinstance(explicit_target.get("template"), dict):
            targeting["template"].update(explicit_target["template"])
        else:
            for key in ("type", "size", "units"):
                if key in explicit_target:
                    targeting["template"][key] = explicit_target[key]
        if isinstance(explicit_target.get("affects"), dict):
            targeting["affects"].update(explicit_target["affects"])
        if "count" in explicit_target:
            targeting["affects"]["count"] = explicit_target["count"]

    return {
        "activity_name": str(explicit.get("activity_name") or ""),
        "activity_type": str(explicit.get("activity_type") or ""),
        "passive": bool(explicit.get("passive", False)),
        "attack": attack,
        "save": save,
        "damage": normalized_damage,
        "healing": healing,
        "uses": uses,
        "activation": activation,
        "duration": duration,
        "targeting": targeting,
        "on_save": explicit.get("on_save") or _on_save(text),
        "consumption": deepcopy(explicit.get("consumption")),
        "resource": deepcopy(explicit.get("resource")),
        "roll": deepcopy(explicit.get("roll")),
        "description": deepcopy(
            explicit.get("description", explicit.get("chat_flavor"))
        ),
        "effects": deepcopy(explicit.get("effects"))
        if isinstance(explicit.get("effects"), list)
        else [],
        "midi_properties": deepcopy(explicit.get("midi_properties")),
        "auto_target_action": str(
            explicit.get("auto_target_action") or ""
        ),
        "auto_target_type": str(explicit.get("auto_target_type") or ""),
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
        "other_activity_id": str(
            explicit.get("other_activity_id") or ""
        ),
        "other_activity_as_parent_type": explicit.get(
            "other_activity_as_parent_type"
        ),
        "consume_uses": explicit.get("consume_uses"),
        "activities": deepcopy(explicit.get("activities"))
        if isinstance(explicit.get("activities"), list)
        else [],
        "text": text,
    }


def _apply_uses(
    system: dict[str, Any],
    mechanics: dict[str, Any],
    report: BuildReport,
    path: str,
) -> bool:
    uses_data = mechanics.get("uses")
    if not isinstance(uses_data, dict) or not uses_data:
        return False
    uses = _ensure_dict(system, "uses", report, path)
    old = deepcopy(uses)
    maximum = _formula(uses_data.get("max"))
    if maximum:
        uses["max"] = maximum
    uses.setdefault("spent", 0)
    recovery = uses_data.get("recovery")
    if isinstance(recovery, list):
        uses["recovery"] = deepcopy(recovery)
    else:
        uses.setdefault("recovery", [])
    if uses != old:
        report.change(f"{path}.uses", "configured_uses", old, deepcopy(uses))
        return True
    return False


def _build_save_activity(
    mechanics: dict[str, Any],
    activity_id: str = "dnd5eactivity000",
) -> dict[str, Any] | None:
    save = mechanics.get("save")
    if not isinstance(save, dict):
        return None
    ability = _normalize_ability(save.get("ability"))
    dc = _formula(save.get("dc"))
    dc_formula = _formula(save.get("dc_formula", save.get("formula")))
    calculation = str(save.get("calculation") or "").strip()
    if not ability or not (dc or dc_formula or calculation):
        return None

    activity = _base_activity(activity_id, "save")
    _apply_activity_common(activity, mechanics)

    activity["save"]["ability"] = [ability]
    if dc_formula:
        activity["save"]["dc"] = {
            "calculation": "",
            "formula": dc_formula,
        }
    elif dc and dc != "spellcasting":
        activity["save"]["dc"] = {
            "calculation": "",
            "formula": dc,
        }
    else:
        activity["save"]["dc"] = {
            "calculation": calculation or "spellcasting",
            "formula": "",
        }
    on_save = str(
        mechanics.get("on_save") or save.get("on_save") or "none"
    )
    activity["damage"]["onSave"] = (
        on_save if on_save in {"none", "half", "full"} else "none"
    )
    for damage in mechanics.get("damage") or []:
        activity["damage"]["parts"].append(
            _formula_parts(str(damage["formula"]), str(damage.get("type") or ""))
        )

    return activity


def _build_attack_activity(
    mechanics: dict[str, Any],
    activity_id: str = "dnd5eactivity000",
) -> dict[str, Any] | None:
    attack = mechanics.get("attack")
    if not isinstance(attack, dict):
        return None

    activity = _base_activity(activity_id, "attack")
    _apply_activity_common(activity, mechanics)
    activity["attack"]["ability"] = str(attack.get("ability") or "")
    activity["attack"]["bonus"] = str(attack.get("bonus") or "")
    activity["attack"]["flat"] = bool(attack.get("flat", False))
    attack_type = str(attack.get("type") or "melee").casefold()
    if attack_type not in {"melee", "ranged"}:
        attack_type = "melee"
    classification = str(
        attack.get("classification") or "weapon"
    ).casefold()
    if classification not in {"weapon", "spell"}:
        classification = "weapon"
    activity["attack"]["type"]["value"] = attack_type
    activity["attack"]["type"]["classification"] = classification

    for part in mechanics.get("damage") or []:
        if not isinstance(part, dict):
            continue
        formula = str(part.get("formula") or "").strip()
        if formula:
            activity["damage"]["parts"].append(
                _formula_parts(formula, str(part.get("type") or ""))
            )
    return activity


def _apply_activity_common(
    activity: dict[str, Any],
    mechanics: dict[str, Any],
) -> None:
    activity["name"] = str(mechanics.get("activity_name") or "")
    activation = mechanics.get("activation") or {}
    activation_type = str(activation.get("type") or "action")
    if activation_type not in ACTIVATION_TYPES:
        activation_type = "action"
    value = activation.get("value")
    activity["activation"]["type"] = activation_type
    activity["activation"]["value"] = (
        None
        if value is None and activation_type in {"special", "none"}
        else _integer(value, 1)
    )
    activity["activation"]["condition"] = str(activation.get("condition") or "")
    activity["activation"]["override"] = bool(activation)

    duration = mechanics.get("duration") or {}
    if duration:
        activity["duration"]["value"] = str(duration.get("value") or "")
        activity["duration"]["units"] = str(duration.get("units") or "inst")

    targeting = mechanics.get("targeting") or {}
    range_data = targeting.get("range") or {}
    if "value" in activity["range"]:
        activity["range"]["value"] = str(range_data.get("value") or "")
    activity["range"]["units"] = str(range_data.get("units") or "self")
    template_data = targeting.get("template") or {}
    activity["target"]["template"].update(
        {
            key: (
                str(value)
                if key in {"count", "size", "width", "height"}
                and value is not None
                else value
            )
            for key, value in template_data.items()
            if key in activity["target"]["template"]
        }
    )
    affects = targeting.get("affects") or {}
    activity["target"]["affects"].update(
        {
            key: str(value) if key == "count" and value is not None else value
            for key, value in affects.items()
            if key in activity["target"]["affects"]
        }
    )
    if "prompt" in targeting:
        activity["target"]["prompt"] = bool(targeting["prompt"])
    if targeting:
        activity["target"]["override"] = True

    description = mechanics.get(
        "description",
        mechanics.get("chat_flavor"),
    )
    if isinstance(description, dict):
        activity["description"]["chatFlavor"] = str(
            description.get("chatFlavor")
            or description.get("chat")
            or description.get("value")
            or ""
        )
    elif isinstance(description, str):
        activity["description"]["chatFlavor"] = description

    uses_data = mechanics.get("uses")
    activity_scoped_uses = bool(mechanics.get("_activity_scoped_uses"))
    if activity_scoped_uses and isinstance(uses_data, dict):
        maximum = _formula(uses_data.get("max"))
        if maximum:
            activity["uses"]["max"] = maximum
        activity["uses"]["spent"] = max(
            0, _integer(uses_data.get("spent"), 0)
        )
        recovery = uses_data.get("recovery")
        if isinstance(recovery, list):
            activity["uses"]["recovery"] = deepcopy(recovery)

    consumption = mechanics.get("consumption")
    if isinstance(consumption, list):
        activity["consumption"]["targets"] = deepcopy(consumption)
    else:
        resource = mechanics.get("resource")
        if isinstance(resource, dict) and resource.get("target"):
            resource_type = str(resource.get("type") or "attribute")
            if resource_type == "pool":
                namespace = activity["flags"].setdefault(
                    "foundry-content-generator", {}
                )
                namespace["resourcePool"] = {
                    "key": str(resource["target"]),
                    "cost": str(resource.get("value") or "1"),
                }
            else:
                activity["consumption"]["targets"] = [
                    {
                        "type": resource_type,
                        "target": str(resource["target"]),
                        "value": str(resource.get("value") or "1"),
                        "scaling": {"mode": "", "formula": ""},
                    }
                ]
        else:
            consume_uses = mechanics.get("_auto_consume_uses")
            if consume_uses is None:
                consume_uses = mechanics.get("consume_uses")
            if consume_uses is None:
                # ``None`` means that the input did not override the default.
                # A single activity backed by item uses must consume one use.
                consume_uses = True
            if (
                bool(consume_uses)
                and isinstance(uses_data, dict)
                and _formula(uses_data.get("max"))
            ):
                activity["consumption"]["targets"] = [
                    {
                        "type": (
                            "activityUses"
                            if activity_scoped_uses
                            else "itemUses"
                        ),
                        "target": "",
                        "value": "1",
                        "scaling": {"mode": "", "formula": ""},
                    }
                ]

    midi_properties = mechanics.get("midi_properties")
    if isinstance(midi_properties, dict):
        activity["midiProperties"].update(
            {
                key: deepcopy(value)
                for key, value in midi_properties.items()
                if key in activity["midiProperties"]
            }
        )
    if mechanics.get("auto_target_action"):
        activity["midiProperties"]["autoTargetAction"] = str(
            mechanics["auto_target_action"]
        )
    if mechanics.get("auto_target_type"):
        activity["midiProperties"]["autoTargetType"] = str(
            mechanics["auto_target_type"]
        )
    midi_compat.apply_activity_mechanics(activity, mechanics)

    # Midi-QOL различает визуальное выделение токенов шаблоном области и
    # фактическое добавление этих токенов в workflow activity. При
    # confirmTargets="default" D&D5e 5.3.3 иногда оставляет карточку без целей.
    # Поэтому явно автоматически нацеленный шаблон по умолчанию подтверждает
    # уже вычисленный список. Автор может отключить это через
    # midi_properties.confirmTargets="never".
    template_type = str(
        activity.get("target", {}).get("template", {}).get("type") or ""
    ).strip()
    auto_target_action = str(
        activity.get("midiProperties", {}).get("autoTargetAction") or "default"
    )
    confirm_targets = str(
        activity.get("midiProperties", {}).get("confirmTargets") or "default"
    )
    if (
        template_type
        and auto_target_action not in {"default", "none"}
        and confirm_targets == "default"
    ):
        activity["midiProperties"]["confirmTargets"] = "always"
    elif (
        template_type
        and not bool(
            activity.get("target", {})
            .get("affects", {})
            .get("choice", False)
        )
        and auto_target_action == "default"
    ):
        # Обычная область без ручного выбора должна сразу передавать найденные
        # токены в workflow Midi-QOL. Для выборочных областей это поведение
        # намеренно не включается.
        activity["midiProperties"]["autoTargetAction"] = (
            "alwaysIgnoreDefeated"
        )
        if confirm_targets == "default":
            activity["midiProperties"]["confirmTargets"] = "always"


def _build_heal_activity(
    mechanics: dict[str, Any],
    activity_id: str = "dnd5eactivity000",
) -> dict[str, Any] | None:
    healing = mechanics.get("healing")
    if not isinstance(healing, dict):
        return None
    formula = str(healing.get("formula") or "").strip()
    if not formula:
        return None
    healing_type = str(healing.get("type") or "healing")
    activity = _base_activity(activity_id, "heal")
    _apply_activity_common(activity, mechanics)
    activity["range"]["units"] = str(
        ((mechanics.get("targeting") or {}).get("range") or {}).get("units")
        or "self"
    )
    if not ((mechanics.get("targeting") or {}).get("affects") or {}).get("type"):
        activity["target"]["affects"]["type"] = "self"
    activity["healing"] = _healing_parts(formula, healing_type)
    return activity


def _build_damage_activity(
    mechanics: dict[str, Any],
    activity_id: str = "dnd5eactivity000",
) -> dict[str, Any] | None:
    damage = mechanics.get("damage")
    if not isinstance(damage, list) or not damage:
        return None

    activity = _base_activity(activity_id, "damage")
    _apply_activity_common(activity, mechanics)
    roll = mechanics.get("roll")
    if not activity["name"] and isinstance(roll, dict):
        activity["name"] = str(roll.get("name") or "")
    for part in damage:
        if not isinstance(part, dict):
            continue
        formula = str(part.get("formula") or "").strip()
        if formula:
            activity["damage"]["parts"].append(
                _formula_parts(formula, str(part.get("type") or ""))
            )
    return activity if activity["damage"]["parts"] else None


def _build_utility_activity(
    mechanics: dict[str, Any],
    activity_id: str = "dnd5eactivity000",
) -> dict[str, Any]:
    activity = _base_activity(activity_id, "utility")
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


def _activity_id(index: int) -> str:
    # Foundry document IDs must contain exactly 16 alphanumeric characters.
    # The previous ``index * 100`` scheme overflowed at the 11th activity.
    if index < 0 or index > 999:
        raise ValueError("Поддерживается не более 1000 активностей на особенность.")
    return f"dnd5eactivity{index:03d}"


def _activity_mechanics(
    parent: dict[str, Any],
    spec: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    result = deepcopy(parent)
    result.pop("activities", None)
    result["_auto_consume_uses"] = index == 0
    result["_activity_scoped_uses"] = "uses" in spec
    for key, value in spec.items():
        if key != "type":
            result[key] = deepcopy(value)
    if "consume_uses" in spec:
        result["_auto_consume_uses"] = bool(spec["consume_uses"])
    if "consumption" in spec or "resource" in spec:
        result["_auto_consume_uses"] = False
    return result


def _infer_resource(mechanics: dict[str, Any], feat_name: str) -> None:
    if (
        isinstance(mechanics.get("resource"), dict)
        or isinstance(mechanics.get("consumption"), list)
    ):
        return
    combined = f"{feat_name} {mechanics.get('text') or ''}".casefold().replace("ё", "е")
    if re.search(
        r"(?:легендарн\w*\s+(?:стойкост|устойчивост|сопротивлен)|"
        r"(?:стойкост|устойчивост|сопротивлен)\w*\s+легендарн\w*|"
        r"legendary resistance)",
        combined,
    ):
        mechanics["resource"] = {
            "type": "attribute",
            "target": "resources.legres.value",
            "value": "1",
        }
        return

    activation = mechanics.get("activation")
    if (
        isinstance(activation, dict)
        and str(activation.get("type") or "").casefold() == "legendary"
    ):
        mechanics["resource"] = {
            "type": "attribute",
            "target": "resources.legact.value",
            "value": str(max(1, _integer(activation.get("value"), 1))),
        }


def _build_activities(
    mechanics: dict[str, Any],
    feat_name: str,
    report: BuildReport,
) -> list[dict[str, Any]]:
    if mechanics.get("passive"):
        return []
    specs = mechanics.get("activities")
    result: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    if isinstance(specs, list) and specs:
        for index, spec in enumerate(specs):
            if not isinstance(spec, dict):
                report.warning(
                    f"{feat_name}: activity #{index + 1} пропущена — "
                    "ожидался JSON-объект."
                )
                continue
            activity_type = str(spec.get("type") or "").casefold()
            if activity_type not in ACTIVITY_TYPES:
                report.warning(
                    f"{feat_name}: неизвестный тип activity "
                    f"«{activity_type or 'пусто'}»; элемент #{index + 1} пропущен."
                )
                continue
            data = _activity_mechanics(mechanics, spec, index)
            _infer_resource(data, feat_name)
            raw_activity_id = str(spec.get("_id") or "").strip()
            if raw_activity_id and not re.fullmatch(
                r"[A-Za-z0-9]{16}", raw_activity_id
            ):
                report.warning(
                    f"{feat_name}: некорректный _id activity "
                    f"«{raw_activity_id}» заменён автоматически."
                )
                raw_activity_id = ""
            activity_id = raw_activity_id or _activity_id(index)
            if activity_id in used_ids:
                report.warning(
                    f"{feat_name}: повторяющийся _id activity "
                    f"«{activity_id}» заменён автоматически."
                )
                activity_id = _activity_id(index)
                suffix = index
                while activity_id in used_ids:
                    suffix += 1
                    activity_id = _activity_id(suffix)
            used_ids.add(activity_id)
            if activity_type == "attack":
                activity = _build_attack_activity(data, activity_id)
            elif activity_type == "save":
                activity = _build_save_activity(data, activity_id)
            elif activity_type == "damage":
                activity = _build_damage_activity(data, activity_id)
            elif activity_type == "heal":
                activity = _build_heal_activity(data, activity_id)
            elif activity_type == "utility":
                activity = _build_utility_activity(data, activity_id)
            else:
                activity = None
            if activity is not None:
                result.append(activity)
            else:
                report.warning(
                    f"{feat_name}: activity «{spec.get('activity_name') or activity_type}» "
                    "не создана — отсутствуют обязательные механические поля."
                )
        return result

    _infer_resource(mechanics, feat_name)
    explicit_type = str(mechanics.get("activity_type") or "").casefold()
    if explicit_type and explicit_type not in ACTIVITY_TYPES:
        report.warning(
            f"{feat_name}: неизвестный activity_type "
            f"«{explicit_type}»; активность не создана."
        )
        return []
    if explicit_type:
        if explicit_type == "attack":
            activity = _build_attack_activity(mechanics, _activity_id(0))
        elif explicit_type == "save":
            activity = _build_save_activity(mechanics, _activity_id(0))
        elif explicit_type == "damage":
            activity = _build_damage_activity(mechanics, _activity_id(0))
        elif explicit_type == "heal":
            activity = _build_heal_activity(mechanics, _activity_id(0))
        else:
            activity = _build_utility_activity(mechanics, _activity_id(0))
        if activity is None:
            report.warning(
                f"{feat_name}: activity_type «{explicit_type}» указан, "
                "но обязательных данных для него недостаточно."
            )
            return []
        return [activity]
    if isinstance(mechanics.get("attack"), dict) and mechanics["attack"]:
        attack_activity = _build_attack_activity(mechanics, _activity_id(0))
        if attack_activity is not None:
            return [attack_activity]
    save_activity = _build_save_activity(mechanics, _activity_id(0))
    if save_activity is not None:
        return [save_activity]
    heal_activity = _build_heal_activity(mechanics, _activity_id(0))
    if heal_activity is not None:
        return [heal_activity]

    damage_activity = _build_damage_activity(mechanics, _activity_id(0))
    if damage_activity is not None:
        return [damage_activity]

    activation = mechanics.get("activation")
    activation_type = (
        str(activation.get("type") or "") if isinstance(activation, dict) else ""
    )
    if (
        activation_type in {"bonus", "reaction", "legendary", "lair", "special"}
        or isinstance(mechanics.get("resource"), dict)
        or isinstance(mechanics.get("consumption"), list)
    ):
        return [_build_utility_activity(mechanics, _activity_id(0))]
    return []


def _effect_id(index: int) -> str:
    if index < 0 or index > 99999:
        raise ValueError("Поддерживается не более 100000 эффектов на особенность.")
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


def _effect_duration(
    value: Any,
    feat_duration: dict[str, Any],
) -> dict[str, Any]:
    result = {
        "startTime": None,
        "seconds": None,
        "combat": None,
        "rounds": None,
        "turns": None,
        "startRound": None,
        "startTurn": None,
    }
    if isinstance(value, dict) and any(
        key in value for key in ("seconds", "rounds", "turns")
    ):
        for key in result:
            if key in value:
                result[key] = deepcopy(value[key])
        return result

    source = value if isinstance(value, dict) else feat_duration
    if not isinstance(source, dict):
        return result
    number = _integer(source.get("value"), 0)
    if number <= 0:
        return result
    units = str(source.get("units") or "inst").casefold()
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
    feat_name: str,
    feat_duration: dict[str, Any],
) -> dict[str, Any]:
    raw_id = str(spec.get("_id") or "").strip()
    effect_id = (
        raw_id
        if re.fullmatch(r"[A-Za-z0-9]{16}", raw_id)
        else _effect_id(index)
    )
    flags = midi_compat.effect_flags(spec)
    return {
        "_id": effect_id,
        "name": str(spec.get("name") or feat_name),
        "img": str(spec.get("img") or ""),
        "type": "base",
        "system": {},
        "changes": _effect_changes(spec.get("changes")),
        "disabled": bool(spec.get("disabled", False)),
        "duration": _effect_duration(spec.get("duration"), feat_duration),
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
    feat_name: str,
    report: BuildReport,
    existing_effects: list[Any] | None = None,
) -> list[dict[str, Any]]:
    specs = midi_compat.collect_effect_specs(mechanics)
    if not specs:
        return []
    feat_duration = (
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
                f"{feat_name}: эффект #{index + 1} пропущен — "
                "ожидался JSON-объект."
            )
            continue
        raw_effect_id = str(spec.get("_id") or "").strip()
        if raw_effect_id and not re.fullmatch(
            r"[A-Za-z0-9]{16}", raw_effect_id
        ):
            report.warning(
                f"{feat_name}: некорректный _id эффекта "
                f"«{raw_effect_id}» заменён автоматически."
            )
        effect = _build_effect(spec, index, feat_name, feat_duration)
        if effect["_id"] in used_ids:
            report.warning(
                f"{feat_name}: повторяющийся _id эффекта "
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
                f"{feat_name}: эффект «{effect['name']}» создан, "
                "но указанная activity не найдена."
            )
        elif not effect["transfer"] and not targets:
            report.warning(
                f"{feat_name}: применяемый эффект «{effect['name']}» "
                "не привязан к активности."
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


def _audit_existing_activities(
    activities: dict[str, Any],
    feat_name: str,
    report: BuildReport,
    path: str,
) -> None:
    for key, activity in activities.items():
        if not isinstance(activity, dict):
            report.warning(
                f"{feat_name}: существующая activity «{key}» не является объектом."
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
                f"{feat_name}: существующая activity «{key}» имеет "
                f"неизвестный тип «{activity_type or 'пусто'}»."
            )
        raw_id = str(activity.get("_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9]{16}", raw_id):
            report.warning(
                f"{feat_name}: существующая activity «{key}» имеет "
                f"некорректный _id «{raw_id or 'пусто'}»."
            )
        elif raw_id != str(key):
            report.warning(
                f"{feat_name}: ключ activity «{key}» не совпадает "
                f"с её _id «{raw_id}»."
            )


def _normalize_feat(
    feat: dict[str, Any],
    report: BuildReport,
    path: str,
) -> None:
    name = feat.get("name")
    if not isinstance(name, str) or not name.strip():
        old = name
        feat["name"] = "Безымянная особенность"
        report.change(f"{path}.name", "filled_required_name", old, feat["name"])
    else:
        feat["name"] = name.strip()

    _default(
        feat,
        "img",
        "systems/dnd5e/icons/svg/items/feature.svg",
        report,
        path,
    )
    _default(feat, "folder", None, report, path)
    _default(feat, "flags", {}, report, path)
    _default(
        feat,
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
    old_type = feat.get("type")
    if old_type != "feat":
        feat["type"] = "feat"
        report.change(f"{path}.type", "normalized_item_type", old_type, "feat")

    system = _ensure_dict(feat, "system", report, path)
    feat_effects = _ensure_list(feat, "effects", report, path)

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

    uses = _ensure_dict(system, "uses", report, f"{path}.system")
    _default(uses, "max", "", report, f"{path}.system.uses")
    _default(uses, "spent", 0, report, f"{path}.system.uses")
    _ensure_list(uses, "recovery", report, f"{path}.system.uses")

    feat_type = _ensure_dict(system, "type", report, f"{path}.system")
    _default(feat_type, "value", "monster", report, f"{path}.system.type")
    _default(feat_type, "subtype", "", report, f"{path}.system.type")
    _default(system, "requirements", "", report, f"{path}.system")
    _default(system, "properties", [], report, f"{path}.system")
    _default(system, "identifier", _slug(feat["name"]), report, f"{path}.system")
    _default(system, "advancement", {}, report, f"{path}.system")
    _default(system, "crewed", False, report, f"{path}.system")
    _default(system, "enchant", {}, report, f"{path}.system")
    prerequisites = _ensure_dict(
        system, "prerequisites", report, f"{path}.system"
    )
    _default(prerequisites, "level", None, report, f"{path}.system.prerequisites")
    _default(prerequisites, "items", [], report, f"{path}.system.prerequisites")
    _default(
        prerequisites, "repeatable", False, report, f"{path}.system.prerequisites"
    )

    activities = system.get("activities")
    if isinstance(activities, list):
        converted = {}
        for index, activity in enumerate(activities):
            if isinstance(activity, dict):
                activity_id = str(activity.get("_id") or f"dnd5eactivity{index:03d}")
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
            f"{path}.system.activities", "created_object", old, deepcopy(activities)
        )

    before = len(activities)
    if before:
        _audit_existing_activities(
            activities,
            feat["name"],
            report,
            f"{path}.system.activities",
        )
        report.feats.append(
            FeatResult(
                feat["name"],
                "preserved",
                before,
                before,
                "Существующие activities сохранены без замены.",
            )
        )
        return

    explicit_mechanics = _extract_explicit_mechanics(feat)
    if _was_processed_without_activity(feat) and not explicit_mechanics:
        report.feats.append(
            FeatResult(
                feat["name"],
                "preserved",
                0,
                0,
                "Ранее обработанная пассивная или ручная особенность сохранена.",
            )
        )
        return

    mechanics = _merged_mechanics(feat)
    _consume_builder_mechanics(feat, system, report, path)
    uses_changed = _apply_uses(
        system, mechanics, report, f"{path}.system"
    )
    built_activities = _build_activities(mechanics, feat["name"], report)
    built_effects = _build_effects(
        mechanics,
        built_activities,
        feat["name"],
        report,
        feat_effects,
    )
    for effect in built_effects:
        feat_effects.append(effect)
        report.change(
            f"{path}.effects[{len(feat_effects) - 1}]",
            "created_active_effect",
            None,
            deepcopy(effect),
        )
    if built_activities:
        automated_conditions = {
            status
            for effect in built_effects
            for status in effect.get("statuses", [])
        }
        conditions = [
            condition
            for condition in _detected_conditions(
                str(mechanics.get("text") or "")
            )
            if condition not in automated_conditions
        ]
        for activity in built_activities:
            activities[activity["_id"]] = activity
            report.change(
                f"{path}.system.activities.{activity['_id']}",
                f"created_{activity['type']}_activity",
                None,
                deepcopy(activity),
            )
        activity_types = [activity["type"] for activity in built_activities]
        report.feats.append(
            FeatResult(
                feat["name"],
                "created_activities",
                0,
                len(built_activities),
                "Созданы activities: " + ", ".join(activity_types) + "."
                + (
                    f" Active Effects: {len(built_effects)}."
                    if built_effects
                    else ""
                )
                + (
                    " В тексте также упомянуты состояния: "
                    + ", ".join(conditions)
                    + "."
                    if conditions
                    else ""
                ),
            )
        )
        return

    text = mechanics.get("text") or ""
    conditions = _detected_conditions(text)
    has_condition = bool(conditions)
    if built_effects:
        status = "created_effects"
        message = (
            f"Созданы Active Effects: {len(built_effects)}; "
            "нажимаемая активность не требуется."
        )
    elif uses_changed:
        status = "uses_only"
        message = "Настроены использования; безопасной активности не найдено."
    elif has_condition:
        status = "manual_effect"
        message = "Найдено состояние, но его автоматический эффект не создавался."
    else:
        status = "passive_or_manual"
        message = "Особенность сохранена как пассивная или ручная."
    _mark_processed_without_activity(feat)
    report.feats.append(FeatResult(feat["name"], status, 0, 0, message))


def normalize_document(
    source: dict[str, Any],
    source_name: str = "",
) -> tuple[dict[str, Any], BuildReport, str]:
    """Нормализует актёра или отдельную особенность."""
    if not isinstance(source, dict):
        raise FeatBuilderError("Корень JSON должен быть объектом.")

    document = deepcopy(source)
    report = BuildReport(source=source_name)
    document_type = document.get("type")

    if document_type == "feat":
        _normalize_feat(document, report, "$")
        return document, report, "feat"

    items = document.get("items")
    if not isinstance(items, list):
        raise FeatBuilderError(
            "Ожидался type='feat' либо JSON актёра с массивом items."
        )

    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("type") == "feat":
            _normalize_feat(item, report, f"$.items[{index}]")
    return document, report, "actor"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except FileNotFoundError as error:
        raise FeatBuilderError(f"Файл не найден: {path}") from error
    except json.JSONDecodeError as error:
        raise FeatBuilderError(
            f"Ошибка JSON в {path}, строка {error.lineno}, столбец {error.colno}: "
            f"{error.msg}"
        ) from error
    except OSError as error:
        raise FeatBuilderError(f"Не удалось прочитать {path}: {error}") from error
    if not isinstance(data, dict):
        raise FeatBuilderError("Корень JSON должен быть объектом.")
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
        raise FeatBuilderError(f"Не удалось записать {path}: {error}") from error


def _default_input() -> Path:
    candidates = (
        Path("output/actors/npc_foundry.json"),
        Path("input/npc.json"),
        Path("input/feat.json"),
        Path("npc.json"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[1]


def _default_output(document: dict[str, Any], kind: str) -> Path:
    name = _safe_filename(str(document.get("name") or "Безымянный"))
    if kind == "actor":
        return Path("output/actors") / f"{name}_foundry.json"
    return Path("output/items") / f"{name}_foundry.json"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Нормализует особенности для Foundry VTT 13.351 / D&D5e 5.3.3."
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=None,
        help="JSON актёра или отдельной особенности.",
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
        default=Path("logs/feat_builder_report.json"),
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
            source, source_name=str(source_path)
        )
        if kind == "feat":
            compatibility = midi_compat.audit_document(document)
            if compatibility["errors"]:
                raise FeatBuilderError(
                    "Проверка Midi-QOL/DAE не пройдена: "
                    + "; ".join(compatibility["errors"][:5])
                )
            for warning in compatibility["warnings"]:
                report.warning(f"Midi-QOL/DAE: {warning}")
        output_path = args.output or _default_output(document, kind)
        report.output = str(output_path)
        _atomic_json_write(output_path, document, args.indent)
        _atomic_json_write(args.report, asdict(report), args.indent)
    except FeatBuilderError as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return 1

    counts: dict[str, int] = {}
    for feat in report.feats:
        counts[feat.status] = counts.get(feat.status, 0) + 1
    print(f"Готово: {document.get('name', 'Безымянный')}")
    print(f"JSON: {output_path}")
    print(f"Отчёт: {args.report}")
    if counts:
        summary = ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
        print(f"Особенности: {summary}")
    if report.warnings:
        print(f"Предупреждений: {len(report.warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
