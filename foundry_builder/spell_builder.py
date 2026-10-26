#!/usr/bin/env python3
"""Сборка заклинаний Foundry VTT 13.351 / D&D5e 5.3.3.

Билдер нормализует структуру предмета type="spell" и создаёт рабочие
activities для атак заклинанием, спасбросков, урона, лечения и их
масштабирования от уровня существа или использованной ячейки. Также создаёт
Active Effects и привязывает их к нужным activities.

Билдер принимает:
  * полный JSON актёра и обрабатывает вложенные предметы type="spell";
  * отдельный JSON заклинания type="spell".

Уже существующие activities и effects сохраняются без замены. Для новых
заклинаний точная механика передаётся во временном поле mechanics.

Запуск:
    python spell_builder.py input/npc.json
    python spell_builder.py input/spell.json
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

SCHOOL_ALIASES = {
    "abj": "abj",
    "abjuration": "abj",
    "ограждение": "abj",
    "con": "con",
    "conjuration": "con",
    "вызов": "con",
    "призыв": "con",
    "div": "div",
    "divination": "div",
    "прорицание": "div",
    "enc": "enc",
    "enchantment": "enc",
    "очарование": "enc",
    "evo": "evo",
    "evocation": "evo",
    "воплощение": "evo",
    "ill": "ill",
    "illusion": "ill",
    "иллюзия": "ill",
    "nec": "nec",
    "necromancy": "nec",
    "некромантия": "nec",
    "trs": "trs",
    "transmutation": "trs",
    "преобразование": "trs",
    "трансмутация": "trs",
}

PROPERTY_ALIASES = {
    "v": "vocal",
    "verbal": "vocal",
    "vocal": "vocal",
    "вербальный": "vocal",
    "словесный": "vocal",
    "с": "somatic",
    "s": "somatic",
    "somatic": "somatic",
    "соматический": "somatic",
    "м": "material",
    "m": "material",
    "material": "material",
    "материальный": "material",
    "concentration": "concentration",
    "концентрация": "concentration",
    "ritual": "ritual",
    "ритуал": "ritual",
}

ACTIVATION_ALIASES = {
    "action": "action",
    "действие": "action",
    "bonus": "bonus",
    "bonus action": "bonus",
    "бонусное действие": "bonus",
    "reaction": "reaction",
    "реакция": "reaction",
    "minute": "minute",
    "минута": "minute",
    "hour": "hour",
    "час": "hour",
    "special": "special",
    "особое": "special",
}

DURATION_UNIT_ALIASES = {
    "": "inst",
    "instant": "inst",
    "instantaneous": "inst",
    "inst": "inst",
    "мгновенно": "inst",
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
    "permanent": "perm",
    "perm": "perm",
    "постоянно": "perm",
    "special": "spec",
    "spec": "spec",
    "особая": "spec",
}

RANGE_UNIT_ALIASES = {
    "": "ft",
    "ft": "ft",
    "feet": "ft",
    "фут": "ft",
    "футов": "ft",
    "mi": "mi",
    "mile": "mi",
    "миля": "mi",
    "self": "self",
    "на себя": "self",
    "touch": "touch",
    "касание": "touch",
    "spec": "spec",
    "sight": "spec",
    "видимость": "spec",
    "any": "any",
    "unlimited": "any",
    "неограниченная": "any",
    "special": "spec",
    "особая": "spec",
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

ACTIVITY_TYPES = {"attack", "save", "damage", "heal", "utility"}

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
    "ослепленный": "blinded",
    "charmed": "charmed",
    "очарован": "charmed",
    "deafened": "deafened",
    "оглох": "deafened",
    "оглохший": "deafened",
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
    "ошеломлен": "stunned",
    "unconscious": "unconscious",
    "без сознания": "unconscious",
}

SCALING_MODE_ALIASES = {
    "": "",
    "none": "",
    "off": "",
    "нет": "",
    "whole": "whole",
    "full": "whole",
    "each": "whole",
    "per level": "whole",
    "per_level": "whole",
    "per slot": "whole",
    "per_slot": "whole",
    "slot": "whole",
    "upcast": "whole",
    "cantrip": "whole",
    "полное": "whole",
    "каждый уровень": "whole",
    "half": "half",
    "every two": "half",
    "every_two": "half",
    "каждые два": "half",
}

HTML_PARAGRAPH_RE = re.compile(
    r"^\s*<p(?:\s[^>]*)?>(?P<body>.*?)</p>\s*",
    re.IGNORECASE | re.DOTALL,
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
SPELL_HEADER_LEVEL_RE = re.compile(
    r"(?:\bзаговор\b|\b[1-9](?:\s*[-–—]\s*|\s*)"
    r"(?:й|го)\s+круг\b)",
    re.IGNORECASE,
)
SPELL_HEADER_LABELS = (
    "время накладывания",
    "дистанция",
    "компоненты",
    "длительность",
)
SPELL_HEADER_SCHOOLS = (
    "ограждение",
    "вызов",
    "призыв",
    "прорицание",
    "очарование",
    "воплощение",
    "иллюзия",
    "некромантия",
    "преобразование",
    "трансмутация",
)

AUTO_TARGET_ACTION_ALIASES = {
    "": "default",
    "default": "default",
    "настройки мира": "default",
    "always": "always",
    "всегда": "always",
    "alwaysignoredefeated": "alwaysIgnoreDefeated",
    "always_ignore_defeated": "alwaysIgnoreDefeated",
    "всегда, кроме поверженных": "alwaysIgnoreDefeated",
    "wallsblock": "wallsBlock",
    "walls_block": "wallsBlock",
    "стены блокируют": "wallsBlock",
    "wallsblockignoredefeated": "wallsBlockIgnoreDefeated",
    "walls_block_ignore_defeated": "wallsBlockIgnoreDefeated",
    "стены блокируют, кроме поверженных": "wallsBlockIgnoreDefeated",
    "wallsblockignoreincapacitated": "wallsBlockIgnoreIncapacitated",
    "walls_block_ignore_incapacitated": "wallsBlockIgnoreIncapacitated",
}


class SpellBuilderError(Exception):
    """Ошибка, из-за которой безопасная обработка невозможна."""


@dataclass
class Change:
    path: str
    action: str
    old: Any = None
    new: Any = None


@dataclass
class SpellResult:
    name: str
    status: str
    level: int
    school: str
    activities: int
    message: str


@dataclass
class BuildReport:
    source: str
    output: str = ""
    changes: list[Change] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    spells: list[SpellResult] = field(default_factory=list)

    def change(self, path: str, action: str, old: Any, new: Any) -> None:
        self.changes.append(Change(path, action, old, new))

    def warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _integer(value: Any, default: int = 0) -> int:
    if _is_number(value):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip().replace(",", ".")))
        except ValueError:
            return default
    return default


def _normalize_ability(value: Any) -> str:
    text = str(value or "").casefold().replace("ё", "е").strip()
    return ABILITY_ALIASES.get(text, "")


def _slug(value: str) -> str:
    text = value.casefold().replace("ё", "е")
    transliteration = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l",
        "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s",
        "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch",
        "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e",
        "ю": "yu", "я": "ya",
    }
    text = "".join(transliteration.get(character, character) for character in text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "zaklinanie"


def _safe_filename(value: str) -> str:
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    filename = re.sub(r"\s+", " ", filename)
    if not filename:
        filename = "Безымянное заклинание"
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


def _canonical(
    value: Any,
    aliases: dict[str, str],
    default: str,
) -> str:
    text = str(value or "").casefold().replace("ё", "е").strip()
    return aliases.get(text, default)


def _plain_html_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    text = HTML_TAG_RE.sub("", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _is_redundant_spell_header_paragraph(value: str) -> bool:
    """Определяет начальный абзац с метаданными, уже показанными Foundry."""
    text = _plain_html_text(value).casefold().replace("ё", "е")
    if not text:
        return False

    label_count = sum(label in text for label in SPELL_HEADER_LABELS)
    has_level = bool(SPELL_HEADER_LEVEL_RE.search(text))
    has_school = any(school in text for school in SPELL_HEADER_SCHOOLS)
    return label_count >= 2 or (has_level and (has_school or label_count >= 1))


def _strip_redundant_spell_header(value: str) -> str:
    """Убирает только ведущие HTML-абзацы с системными полями заклинания."""
    remaining = value
    removed = False
    while True:
        match = HTML_PARAGRAPH_RE.match(remaining)
        if match is None or not _is_redundant_spell_header_paragraph(
            match.group("body")
        ):
            break
        remaining = remaining[match.end():]
        removed = True
    return remaining.lstrip() if removed else value


def _normalize_properties(
    system: dict[str, Any],
    report: BuildReport,
    path: str,
) -> None:
    raw = system.get("properties")
    if isinstance(raw, str):
        values = [
            value.strip()
            for value in re.split(r"[,;/]+", raw)
            if value.strip()
        ]
    elif isinstance(raw, list):
        values = raw
    else:
        values = []

    components = system.pop("components", None)
    if isinstance(components, dict):
        component_map = {
            "vocal": ("vocal", "verbal", "v"),
            "somatic": ("somatic", "s"),
            "material": ("material", "m"),
            "concentration": ("concentration",),
            "ritual": ("ritual",),
        }
        for result, keys in component_map.items():
            if any(bool(components.get(key)) for key in keys):
                values.append(result)
        report.change(
            f"{path}.components",
            "consumed_component_aliases",
            components,
            None,
        )

    normalized: list[str] = []
    for value in values:
        property_name = _canonical(value, PROPERTY_ALIASES, "")
        if property_name and property_name not in normalized:
            normalized.append(property_name)

    old = raw
    if old != normalized:
        system["properties"] = normalized
        report.change(f"{path}.properties", "normalized_properties", old, normalized)
    elif "properties" not in system:
        system["properties"] = normalized
        report.change(f"{path}.properties", "filled_default", None, normalized)


def _formula_parts(
    formula: str,
    result_type: str,
    scaling_spec: Any = None,
) -> dict[str, Any]:
    compact = re.sub(r"\s+", "", formula.casefold()).replace("к", "d")
    match = re.fullmatch(
        r"(\d+)d(\d+)(?:([+-])(\d+)|\+(@[a-z0-9_.]+))?",
        compact,
    )
    scaling = _normalize_scaling(scaling_spec)
    if not match:
        return {
            "number": None,
            "denomination": 0,
            "bonus": "",
            "types": [result_type] if result_type else [],
            "custom": {"enabled": True, "formula": formula},
            "scaling": scaling,
        }
    number, denomination, sign, numeric_bonus, reference_bonus = match.groups()
    if reference_bonus:
        bonus = reference_bonus
    elif sign and numeric_bonus:
        bonus = f"{sign}{numeric_bonus}"
    else:
        bonus = ""
    return {
        "number": int(number),
        "denomination": int(denomination),
        "bonus": bonus,
        "types": [result_type] if result_type else [],
        "custom": {"enabled": False, "formula": ""},
        "scaling": scaling,
    }


def _normalize_scaling(value: Any) -> dict[str, Any]:
    """Преобразует краткую разметку ИИ в ScalingField D&D5e 5.3.3.

    Масштабирование хранится одинаково для заговоров и уровневых заклинаний.
    Сам D&D5e определяет число шагов: по уровню владельца для заговора и по
    уровню использованной ячейки для уровневого заклинания.
    """
    if value in (None, "", False):
        return {"mode": "", "number": 1, "formula": ""}

    if value is True:
        return {"mode": "whole", "number": 1, "formula": ""}

    if _is_number(value):
        return {
            "mode": "whole",
            "number": max(0, _integer(value, 1)),
            "formula": "",
        }

    if isinstance(value, str):
        text = value.casefold().replace("ё", "е").strip()
        mode = SCALING_MODE_ALIASES.get(text)
        if mode is not None:
            return {
                "mode": mode,
                "number": 1,
                "formula": "",
            }
        return {
            "mode": "whole",
            "number": 0,
            "formula": value.strip(),
        }

    if not isinstance(value, dict):
        return {"mode": "", "number": 1, "formula": ""}

    raw_mode = str(value.get("mode") or "").casefold().replace("ё", "е").strip()
    has_scaling_value = (
        value.get("number") not in (None, "")
        or bool(str(value.get("formula") or "").strip())
    )
    mode = SCALING_MODE_ALIASES.get(
        raw_mode,
        "whole" if has_scaling_value else "",
    )
    formula = str(value.get("formula") or "").strip()
    if value.get("number") not in (None, ""):
        number = max(0, _integer(value.get("number"), 0))
    else:
        number = 0 if formula else 1
    return {
        "mode": mode,
        "number": number,
        "formula": formula,
    }


def _base_activity(activity_id: str, activity_type: str) -> dict[str, Any]:
    activity: dict[str, Any] = {
        "_id": activity_id,
        "type": activity_type,
        "activation": {
            "type": "action",
            "value": None,
            "override": False,
        },
        "consumption": {
            "targets": [],
            "scaling": {"allowed": False, "max": ""},
            "spellSlot": True,
        },
        "description": {"chatFlavor": ""},
        "duration": {
            "units": "inst",
            "concentration": False,
            "override": False,
        },
        "effects": [],
        "range": {
            "override": False,
            "value": "",
            "units": "self",
            "special": "",
        },
        "target": {
            "prompt": True,
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
                "count": "",
                "type": "creature",
                "choice": False,
                "special": "",
            },
            "override": False,
        },
        "uses": {"spent": 0, "recovery": [], "max": ""},
        "sort": 0,
        "name": "Cast",
        "img": "",
        "visibility": {
            "level": {"min": None, "max": None},
            "requireAttunement": False,
            "requireIdentification": False,
            "requireMagic": False,
        },
        "flags": {},
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
    }
    if activity_type == "attack":
        activity["attack"] = {
            "ability": "",
            "bonus": "",
            "critical": {"threshold": None},
            "flat": False,
            "type": {"value": "ranged", "classification": ""},
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
            "dc": {"calculation": "spellcasting", "formula": ""},
        }
        activity["friendlySave"] = "default"
    elif activity_type == "damage":
        activity["damage"] = {
            "critical": {"allow": False},
            "parts": [],
        }
    elif activity_type == "heal":
        activity["healing"] = _formula_parts("", "healing")
    elif activity_type == "utility":
        activity["roll"] = {
            "formula": "",
            "name": "",
            "prompt": False,
            "visible": False,
        }
    midi_compat.normalize_activity(activity)
    return activity


def _explicit_mechanics(spell: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        spell.get("mechanics"),
        (spell.get("system") or {}).get("mechanics")
        if isinstance(spell.get("system"), dict)
        else None,
    ]
    flags = spell.get("flags")
    if isinstance(flags, dict):
        namespace = flags.get("foundry-content-generator")
        if isinstance(namespace, dict):
            candidates.append(namespace.get("mechanics"))
    for candidate in candidates:
        if isinstance(candidate, dict):
            return deepcopy(candidate)
    return {}


def _activity_id(index: int) -> str:
    # Foundry document IDs must contain exactly 16 alphanumeric characters.
    # Multiplying the index by 100 overflowed to 17 characters at index 10.
    if index < 0 or index > 999:
        raise ValueError("Поддерживается не более 1000 активностей на заклинание.")
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


def _effect_duration(
    value: Any,
    spell_duration: dict[str, Any],
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

    source = value if isinstance(value, dict) else spell_duration
    if not isinstance(source, dict):
        return result

    amount = source.get("value")
    units = _canonical(
        source.get("units"),
        DURATION_UNIT_ALIASES,
        "inst",
    )
    number = _integer(amount, 0)
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
    spell_name: str,
    spell_duration: dict[str, Any],
) -> dict[str, Any]:
    raw_id = str(spec.get("_id") or "").strip()
    effect_id = (
        raw_id
        if re.fullmatch(r"[A-Za-z0-9]{16}", raw_id)
        else _effect_id(index)
    )
    statuses = _normalize_statuses(
        spec.get("statuses", spec.get("status"))
    )
    flags = midi_compat.effect_flags(spec)
    return {
        "_id": effect_id,
        "name": str(spec.get("name") or spell_name),
        "img": str(spec.get("img") or ""),
        "type": "base",
        "system": {},
        "changes": _effect_changes(spec.get("changes")),
        "disabled": bool(spec.get("disabled", False)),
        "duration": _effect_duration(
            spec.get("duration"),
            spell_duration,
        ),
        "description": str(spec.get("description") or ""),
        "origin": str(spec.get("origin") or ""),
        "tint": str(spec.get("tint") or "#ffffff"),
        "transfer": bool(spec.get("transfer", False)),
        "statuses": statuses,
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
    spell_name: str,
    spell_duration: dict[str, Any],
    report: BuildReport,
    existing_effects: list[Any] | None = None,
) -> list[dict[str, Any]]:
    specs = midi_compat.collect_effect_specs(mechanics)
    if not specs:
        return []

    result: list[dict[str, Any]] = []
    used_ids: set[str] = {
        str(effect.get("_id"))
        for effect in (existing_effects or [])
        if isinstance(effect, dict) and effect.get("_id")
    }
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict):
            report.warning(
                f"{spell_name}: эффект #{index + 1} пропущен — "
                "ожидался JSON-объект."
            )
            continue
        raw_effect_id = str(spec.get("_id") or "").strip()
        if raw_effect_id and not re.fullmatch(
            r"[A-Za-z0-9]{16}", raw_effect_id
        ):
            report.warning(
                f"{spell_name}: некорректный _id эффекта "
                f"«{raw_effect_id}» заменён автоматически."
            )
        effect = _build_effect(
            spec,
            index,
            spell_name,
            spell_duration,
        )
        if effect["_id"] in used_ids:
            report.warning(
                f"{spell_name}: повторяющийся _id эффекта "
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
                f"{spell_name}: эффект «{effect['name']}» создан, "
                "но указанная activity не найдена."
            )
        elif not effect["transfer"] and not targets:
            report.warning(
                f"{spell_name}: применяемый эффект «{effect['name']}» "
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


def _activity_mechanics(
    parent: dict[str, Any],
    spec: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    result = deepcopy(parent)
    result.pop("activities", None)
    result["_auto_spell_slot"] = index == 0
    for key, value in spec.items():
        if key != "type":
            result[key] = deepcopy(value)
    if "spell_slot" in spec:
        result["_auto_spell_slot"] = bool(spec["spell_slot"])
    return result


def _apply_activity_common(
    activity: dict[str, Any],
    mechanics: dict[str, Any],
) -> None:
    activity["name"] = str(mechanics.get("activity_name") or "Cast")

    activation = mechanics.get("activation")
    if isinstance(activation, dict):
        raw_activation_type = str(
            activation.get("type") or "action"
        ).casefold().replace("ё", "е").strip()
        activation_type = ACTIVATION_ALIASES.get(
            raw_activation_type,
            raw_activation_type if raw_activation_type in {"none"} else "action",
        )
        value = activation.get("value")
        activity["activation"]["type"] = activation_type
        activity["activation"]["value"] = (
            None
            if value is None and activation_type in {"special", "none"}
            else _integer(value, 1)
        )
        activity["activation"]["condition"] = str(
            activation.get("condition") or ""
        )
        activity["activation"]["override"] = True

    duration = mechanics.get("duration")
    if isinstance(duration, dict):
        activity["duration"]["value"] = str(duration.get("value") or "")
        activity["duration"]["units"] = _canonical(
            duration.get("units"),
            DURATION_UNIT_ALIASES,
            "inst",
        )
        activity["duration"]["concentration"] = bool(
            duration.get("concentration", False)
        )
        activity["duration"]["override"] = True

    targeting = mechanics.get("targeting")
    if not isinstance(targeting, dict):
        targeting = {}

    range_data = targeting.get("range")
    if not isinstance(range_data, dict):
        range_data = mechanics.get("range")
    if isinstance(range_data, dict):
        range_value = range_data.get("value", range_data.get("reach"))
        if range_value not in (None, ""):
            activity["range"]["value"] = str(range_value)
        activity["range"]["units"] = _canonical(
            range_data.get("units"),
            RANGE_UNIT_ALIASES,
            "ft",
        )
        activity["range"]["special"] = str(
            range_data.get("special") or ""
        )
        activity["range"]["override"] = True

    target_data = {
        key: deepcopy(value)
        for key, value in targeting.items()
        if key in {"affects", "template", "prompt"}
    }
    explicit_target = mechanics.get("target")
    if isinstance(explicit_target, dict):
        for key in ("affects", "template", "prompt"):
            if key in explicit_target and key not in target_data:
                target_data[key] = deepcopy(explicit_target[key])
    if isinstance(range_data, dict) and "affects" not in target_data:
        target_data["affects"] = {
            "count": range_data.get("count", ""),
            "type": range_data.get("target_type", "creature"),
        }

    affects = target_data.get("affects")
    if isinstance(affects, dict):
        for key in ("count", "type", "choice", "special"):
            if key in affects:
                value = affects[key]
                activity["target"]["affects"][key] = (
                    str(value)
                    if key == "count" and value not in (None, "")
                    else value
                )
    template = target_data.get("template")
    if isinstance(template, dict):
        for key, value in template.items():
            if key in activity["target"]["template"]:
                activity["target"]["template"][key] = (
                    str(value)
                    if key in {"count", "size", "width", "height"}
                    and value is not None
                    else value
                )
    if "prompt" in target_data:
        activity["target"]["prompt"] = bool(target_data["prompt"])
    if target_data:
        activity["target"]["override"] = True

    description = mechanics.get("description")
    if isinstance(description, dict):
        activity["description"]["chatFlavor"] = str(
            description.get("chatFlavor")
            or description.get("chat")
            or description.get("value")
            or ""
        )

    activity["consumption"]["spellSlot"] = bool(
        mechanics.get(
            "spell_slot",
            mechanics.get("_auto_spell_slot", True),
        )
    )
    consumption = mechanics.get("consumption")
    if isinstance(consumption, list):
        activity["consumption"]["targets"] = deepcopy(consumption)

    raw_auto_target_action = str(
        mechanics.get("auto_target_action") or ""
    ).casefold().replace("ё", "е").strip()
    activity["midiProperties"]["autoTargetAction"] = (
        AUTO_TARGET_ACTION_ALIASES.get(raw_auto_target_action, "default")
    )

    auto_target_type = str(mechanics.get("auto_target_type") or "").strip()
    if auto_target_type:
        activity["midiProperties"]["autoTargetType"] = auto_target_type
    midi_compat.apply_activity_mechanics(activity, mechanics)

    # A placed template may visually highlight tokens before dnd5e/Midi-QOL
    # commits them to the activity workflow.  Force confirmation of the
    # already calculated AoE target set unless the source explicitly selected
    # another confirmation mode.
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


def _damage_parts(mechanics: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    damage = mechanics.get("damage")
    if not isinstance(damage, list):
        return result
    default_scaling = mechanics.get("scaling")
    for part in damage:
        if not isinstance(part, dict):
            continue
        formula = str(part.get("formula") or "").strip()
        if formula:
            result.append(
                _formula_parts(
                    formula,
                    str(part.get("type") or ""),
                    (
                        part.get("scaling")
                        if "scaling" in part
                        else default_scaling
                    ),
                )
            )
    return result


def _build_attack_activity(
    mechanics: dict[str, Any],
    activity_id: str,
) -> dict[str, Any] | None:
    attack = mechanics.get("attack")
    if not isinstance(attack, dict):
        return None
    activity = _base_activity(activity_id, "attack")
    _apply_activity_common(activity, mechanics)
    activity["attack"]["ability"] = str(attack.get("ability") or "")
    activity["attack"]["bonus"] = str(attack.get("bonus") or "")
    activity["attack"]["flat"] = bool(attack.get("flat", False))
    attack_type = str(attack.get("type") or "ranged").casefold()
    if attack_type not in {"melee", "ranged"}:
        attack_type = "ranged"
    activity["attack"]["type"]["value"] = attack_type
    activity["attack"]["type"]["classification"] = str(
        attack.get("classification") or ""
    )
    activity["damage"]["parts"] = _damage_parts(mechanics)
    return activity


def _build_save_activity(
    mechanics: dict[str, Any],
    activity_id: str,
) -> dict[str, Any] | None:
    save = mechanics.get("save")
    if not isinstance(save, dict):
        return None
    ability = _normalize_ability(save.get("ability"))
    if not ability:
        return None
    activity = _base_activity(activity_id, "save")
    _apply_activity_common(activity, mechanics)
    activity["save"]["ability"] = [ability]
    dc = save.get("dc")
    calculation = str(save.get("calculation") or "").strip()
    if dc not in (None, "", "spellcasting"):
        activity["save"]["dc"] = {
            "calculation": "",
            "formula": str(dc),
        }
    else:
        activity["save"]["dc"] = {
            "calculation": calculation or "spellcasting",
            "formula": "",
        }
    on_save = str(mechanics.get("on_save") or save.get("on_save") or "none")
    activity["damage"]["onSave"] = (
        on_save if on_save in {"none", "half", "full"} else "none"
    )
    activity["damage"]["parts"] = _damage_parts(mechanics)
    return activity


def _build_damage_activity(
    mechanics: dict[str, Any],
    activity_id: str,
) -> dict[str, Any] | None:
    parts = _damage_parts(mechanics)
    if not parts:
        return None
    activity = _base_activity(activity_id, "damage")
    _apply_activity_common(activity, mechanics)
    activity["damage"]["parts"] = parts
    return activity


def _build_heal_activity(
    mechanics: dict[str, Any],
    activity_id: str,
) -> dict[str, Any] | None:
    healing = mechanics.get("healing")
    if not isinstance(healing, dict):
        return None
    formula = str(healing.get("formula") or "").strip()
    if not formula:
        return None
    activity = _base_activity(activity_id, "heal")
    _apply_activity_common(activity, mechanics)
    activity["healing"] = _formula_parts(
        formula,
        str(healing.get("type") or "healing"),
        (
            healing.get("scaling")
            if "scaling" in healing
            else mechanics.get("scaling")
        ),
    )
    return activity


def _build_utility_activity(
    mechanics: dict[str, Any],
    activity_id: str,
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


def _build_activity(
    activity_type: str,
    mechanics: dict[str, Any],
    activity_id: str,
) -> dict[str, Any] | None:
    if activity_type == "attack":
        return _build_attack_activity(mechanics, activity_id)
    if activity_type == "save":
        return _build_save_activity(mechanics, activity_id)
    if activity_type == "damage":
        return _build_damage_activity(mechanics, activity_id)
    if activity_type == "heal":
        return _build_heal_activity(mechanics, activity_id)
    if activity_type == "utility":
        return _build_utility_activity(mechanics, activity_id)
    return None


def _build_activities(
    mechanics: dict[str, Any],
    spell_name: str,
    report: BuildReport,
) -> list[dict[str, Any]]:
    specs = mechanics.get("activities")
    result: list[dict[str, Any]] = []
    if isinstance(specs, list) and specs:
        for index, spec in enumerate(specs):
            if not isinstance(spec, dict):
                report.warning(
                    f"{spell_name}: activity #{index + 1} пропущена — "
                    "ожидался JSON-объект."
                )
                continue
            activity_type = str(spec.get("type") or "").casefold()
            if activity_type not in ACTIVITY_TYPES:
                report.warning(
                    f"{spell_name}: неизвестный тип activity "
                    f"«{activity_type or 'пусто'}»; элемент #{index + 1} пропущен."
                )
                continue
            data = _activity_mechanics(mechanics, spec, index)
            raw_activity_id = str(spec.get("_id") or "").strip()
            if raw_activity_id and not re.fullmatch(
                r"[A-Za-z0-9]{16}", raw_activity_id
            ):
                report.warning(
                    f"{spell_name}: некорректный _id activity "
                    f"«{raw_activity_id}» заменён автоматически."
                )
                raw_activity_id = ""
            activity_id = raw_activity_id or _activity_id(index)
            used_ids = {item["_id"] for item in result}
            if activity_id in used_ids:
                report.warning(
                    f"{spell_name}: повторяющийся _id activity "
                    f"«{activity_id}» заменён автоматически."
                )
                replacement_index = index
                activity_id = _activity_id(replacement_index)
                while activity_id in used_ids:
                    replacement_index += 1
                    activity_id = _activity_id(replacement_index)
            activity = _build_activity(
                activity_type,
                data,
                activity_id,
            )
            if activity is not None:
                result.append(activity)
            else:
                report.warning(
                    f"{spell_name}: activity "
                    f"«{spec.get('activity_name') or activity_type}» "
                    "не создана — отсутствуют обязательные механические поля."
                )
        return result

    explicit_type = str(mechanics.get("activity_type") or "").casefold()
    if explicit_type in ACTIVITY_TYPES:
        activity = _build_activity(explicit_type, mechanics, _activity_id(0))
        return [activity] if activity is not None else []
    if isinstance(mechanics.get("attack"), dict):
        activity = _build_attack_activity(mechanics, _activity_id(0))
    elif isinstance(mechanics.get("save"), dict):
        activity = _build_save_activity(mechanics, _activity_id(0))
    elif isinstance(mechanics.get("healing"), dict):
        activity = _build_heal_activity(mechanics, _activity_id(0))
    elif isinstance(mechanics.get("damage"), list):
        activity = _build_damage_activity(mechanics, _activity_id(0))
    else:
        activity = None
    return [activity] if activity is not None else []


def _consume_builder_mechanics(
    spell: dict[str, Any],
    system: dict[str, Any],
    report: BuildReport,
    path: str,
) -> None:
    for metadata_parent, metadata_path in (
        (spell, path),
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

    flags = spell.get("flags")
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
    spell_name: str,
    report: BuildReport,
    path: str,
) -> None:
    for key, activity in activities.items():
        if not isinstance(activity, dict):
            report.warning(
                f"{spell_name}: существующая activity «{key}» "
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
        if activity_type not in ACTIVITY_TYPES:
            report.warning(
                f"{spell_name}: существующая activity «{key}» имеет "
                f"неизвестный тип «{activity_type or 'пусто'}»."
            )
        raw_id = str(activity.get("_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9]{16}", raw_id):
            report.warning(
                f"{spell_name}: существующая activity «{key}» имеет "
                f"некорректный _id «{raw_id or 'пусто'}»."
            )
        elif raw_id != str(key):
            report.warning(
                f"{spell_name}: ключ activity «{key}» не совпадает "
                f"с её _id «{raw_id}»."
            )


def _normalize_spell(
    spell: dict[str, Any],
    report: BuildReport,
    path: str,
) -> None:
    name = spell.get("name")
    if not isinstance(name, str) or not name.strip():
        old = name
        spell["name"] = "Безымянное заклинание"
        report.change(f"{path}.name", "filled_required_name", old, spell["name"])
    else:
        spell["name"] = name.strip()

    _default(spell, "img", "icons/svg/book.svg", report, path)
    _default(spell, "folder", None, report, path)
    _default(spell, "flags", {}, report, path)
    _default(
        spell,
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

    old_type = spell.get("type")
    if old_type != "spell":
        spell["type"] = "spell"
        report.change(f"{path}.type", "normalized_item_type", old_type, "spell")

    system = _ensure_dict(spell, "system", report, path)
    spell_effects = _ensure_list(spell, "effects", report, path)

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
    description_value = description_data.get("value")
    if isinstance(description_value, str):
        cleaned_description = _strip_redundant_spell_header(description_value)
        if cleaned_description != description_value:
            description_data["value"] = cleaned_description
            report.change(
                f"{path}.system.description.value",
                "removed_redundant_spell_header",
                description_value,
                cleaned_description,
            )

    source = _ensure_dict(system, "source", report, f"{path}.system")
    _default(source, "custom", "", report, f"{path}.system.source")
    _default(source, "book", "", report, f"{path}.system.source")
    _default(source, "page", "", report, f"{path}.system.source")
    _default(source, "license", "", report, f"{path}.system.source")
    _default(source, "rules", "2024", report, f"{path}.system.source")
    _default(source, "revision", 1, report, f"{path}.system.source")

    old_level = system.get("level")
    level = max(0, min(9, _integer(old_level, 0)))
    if old_level != level:
        system["level"] = level
        report.change(f"{path}.system.level", "normalized_level", old_level, level)

    old_school = system.get("school")
    school = _canonical(old_school, SCHOOL_ALIASES, "")
    if old_school != school:
        system["school"] = school
        report.change(f"{path}.system.school", "normalized_school", old_school, school)
    if not school:
        report.warning(
            f"{spell['name']}: школа заклинания не указана или не распознана."
        )

    activation = _ensure_dict(system, "activation", report, f"{path}.system")
    old_activation_type = activation.get("type")
    activation_type = _canonical(
        old_activation_type, ACTIVATION_ALIASES, "action"
    )
    if old_activation_type != activation_type:
        activation["type"] = activation_type
        report.change(
            f"{path}.system.activation.type",
            "normalized_activation_type",
            old_activation_type,
            activation_type,
        )
    _default(activation, "value", 1, report, f"{path}.system.activation")
    _default(activation, "condition", "", report, f"{path}.system.activation")

    duration = _ensure_dict(system, "duration", report, f"{path}.system")
    old_duration_units = duration.get("units")
    duration_units = _canonical(
        old_duration_units, DURATION_UNIT_ALIASES, "inst"
    )
    if old_duration_units != duration_units:
        duration["units"] = duration_units
        report.change(
            f"{path}.system.duration.units",
            "normalized_duration_units",
            old_duration_units,
            duration_units,
        )
    _default(duration, "value", "", report, f"{path}.system.duration")

    spell_range = _ensure_dict(system, "range", report, f"{path}.system")
    old_range_units = spell_range.get("units")
    range_units = _canonical(old_range_units, RANGE_UNIT_ALIASES, "ft")
    if old_range_units != range_units:
        spell_range["units"] = range_units
        report.change(
            f"{path}.system.range.units",
            "normalized_range_units",
            old_range_units,
            range_units,
        )
    if range_units in {"self", "touch", "any", "spec"}:
        if "value" in spell_range and spell_range["value"] not in ("", None):
            old_value = spell_range["value"]
            spell_range.pop("value")
            report.change(
                f"{path}.system.range.value",
                "removed_inapplicable_range_value",
                old_value,
                None,
            )
    else:
        _default(spell_range, "value", "", report, f"{path}.system.range")
    _default(spell_range, "special", "", report, f"{path}.system.range")

    target = _ensure_dict(system, "target", report, f"{path}.system")
    affects = _ensure_dict(target, "affects", report, f"{path}.system.target")
    _default(affects, "type", "creature", report, f"{path}.system.target.affects")
    _default(affects, "count", "", report, f"{path}.system.target.affects")
    _default(affects, "choice", False, report, f"{path}.system.target.affects")
    _default(affects, "special", "", report, f"{path}.system.target.affects")
    template = _ensure_dict(target, "template", report, f"{path}.system.target")
    _default(template, "units", "ft", report, f"{path}.system.target.template")
    _default(template, "contiguous", False, report, f"{path}.system.target.template")
    _default(template, "type", "", report, f"{path}.system.target.template")
    _default(template, "stationary", False, report, f"{path}.system.target.template")

    uses = _ensure_dict(system, "uses", report, f"{path}.system")
    _default(uses, "max", "", report, f"{path}.system.uses")
    _default(uses, "spent", 0, report, f"{path}.system.uses")
    _ensure_list(uses, "recovery", report, f"{path}.system.uses")

    materials = _ensure_dict(system, "materials", report, f"{path}.system")
    _default(materials, "value", "", report, f"{path}.system.materials")
    _default(materials, "consumed", False, report, f"{path}.system.materials")
    _default(materials, "cost", 0, report, f"{path}.system.materials")
    _default(materials, "supply", 0, report, f"{path}.system.materials")
    _normalize_properties(system, report, f"{path}.system")

    activities = system.get("activities")
    if isinstance(activities, list):
        converted: dict[str, Any] = {}
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
        system["activities"] = {}
        activities = system["activities"]
        report.change(
            f"{path}.system.activities",
            "created_object",
            old,
            {},
        )

    _default(system, "identifier", _slug(spell["name"]), report, f"{path}.system")
    _default(system, "method", "spell", report, f"{path}.system")
    old_prepared = system.get("prepared")
    prepared = 1 if old_prepared is None else _integer(old_prepared, 1)
    prepared = 1 if prepared else 0
    if old_prepared != prepared:
        system["prepared"] = prepared
        report.change(
            f"{path}.system.prepared",
            "normalized_prepared",
            old_prepared,
            prepared,
        )

    activity_count = len(activities)
    if activity_count:
        _audit_existing_activities(
            activities,
            spell["name"],
            report,
            f"{path}.system.activities",
        )
        status = "preserved"
        message = "Существующие activities сохранены без замены."
    else:
        mechanics = _explicit_mechanics(spell)
        template_type = str(template.get("type") or "").strip()
        if template_type and not mechanics.get("auto_target_action"):
            mechanics["auto_target_action"] = "alwaysIgnoreDefeated"
        _consume_builder_mechanics(spell, system, report, path)
        built_activities = _build_activities(
            mechanics,
            spell["name"],
            report,
        )
        built_effects = _build_effects(
            mechanics,
            built_activities,
            spell["name"],
            duration,
            report,
            spell_effects,
        )
        for activity in built_activities:
            activities[activity["_id"]] = activity
            report.change(
                f"{path}.system.activities.{activity['_id']}",
                f"created_{activity['type']}_activity",
                None,
                deepcopy(activity),
            )
        for effect in built_effects:
            spell_effects.append(effect)
            report.change(
                f"{path}.effects[{len(spell_effects) - 1}]",
                "created_active_effect",
                None,
                deepcopy(effect),
            )
        activity_count = len(activities)
        if activity_count:
            status = "created_activities"
            types = ", ".join(
                str(activity["type"]) for activity in built_activities
            )
            message = f"Созданы activities: {types}."
            if built_effects:
                message += f" Active Effects: {len(built_effects)}."
        else:
            status = "normalized_metadata"
            message = (
                "Метаданные заклинания нормализованы; "
                "данных для рабочей активности не найдено."
            )
    report.spells.append(
        SpellResult(
            spell["name"],
            status,
            level,
            school,
            activity_count,
            message,
        )
    )


def normalize_document(
    source: dict[str, Any],
    source_name: str = "",
) -> tuple[dict[str, Any], BuildReport, str]:
    """Нормализует актёра или отдельное заклинание."""
    if not isinstance(source, dict):
        raise SpellBuilderError("Корень JSON должен быть объектом.")

    document = deepcopy(source)
    report = BuildReport(source=source_name)
    document_type = document.get("type")

    if document_type == "spell":
        _normalize_spell(document, report, "$")
        return document, report, "spell"

    items = document.get("items")
    if not isinstance(items, list):
        raise SpellBuilderError(
            "Ожидался type='spell' либо JSON актёра с массивом items."
        )

    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("type") == "spell":
            _normalize_spell(item, report, f"$.items[{index}]")
    return document, report, "actor"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except FileNotFoundError as error:
        raise SpellBuilderError(f"Файл не найден: {path}") from error
    except json.JSONDecodeError as error:
        raise SpellBuilderError(
            f"Ошибка JSON в {path}, строка {error.lineno}, "
            f"столбец {error.colno}: {error.msg}"
        ) from error
    except OSError as error:
        raise SpellBuilderError(f"Не удалось прочитать {path}: {error}") from error
    if not isinstance(data, dict):
        raise SpellBuilderError("Корень JSON должен быть объектом.")
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
        raise SpellBuilderError(f"Не удалось записать {path}: {error}") from error


def _default_input() -> Path:
    candidates = (Path("input/spell.json"), Path("input/npc.json"), Path("spell.json"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _default_output(document: dict[str, Any], kind: str) -> Path:
    name = _safe_filename(str(document.get("name") or "Безымянное заклинание"))
    if kind == "actor":
        return Path("output/actors") / f"{name}_foundry.json"
    return Path("output/spells") / f"{name}_foundry.json"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Нормализует заклинания для Foundry VTT 13.351 / D&D5e 5.3.3."
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=None,
        help="JSON актёра или отдельного заклинания.",
    )
    parser.add_argument("-o", "--output", type=Path, help="Путь итогового JSON.")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("logs/spell_builder_report.json"),
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
        if kind == "spell":
            compatibility = midi_compat.audit_document(document)
            if compatibility["errors"]:
                raise SpellBuilderError(
                    "Проверка Midi-QOL/DAE не пройдена: "
                    + "; ".join(compatibility["errors"][:5])
                )
            for warning in compatibility["warnings"]:
                report.warning(f"Midi-QOL/DAE: {warning}")
        output_path = args.output or _default_output(document, kind)
        report.output = str(output_path)
        _atomic_json_write(output_path, document, args.indent)
        _atomic_json_write(args.report, asdict(report), args.indent)
    except SpellBuilderError as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return 1

    counts: dict[str, int] = {}
    for spell in report.spells:
        counts[spell.status] = counts.get(spell.status, 0) + 1
    print(f"Готово: {document.get('name', 'Безымянный')}")
    print(f"JSON: {output_path}")
    print(f"Отчёт: {args.report}")
    if counts:
        summary = ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
        print(f"Заклинания: {summary}")
    if report.warnings:
        print(f"Предупреждений: {len(report.warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
