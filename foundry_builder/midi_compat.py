#!/usr/bin/env python3
"""Совместимость activities и Active Effects с Midi-QOL/DAE.

Целевые версии:
    Foundry VTT 13.351
    D&D5e 5.3.3
    Midi-QOL 13.0.64
    DAE 13.0.29

Модуль не пытается выполнять макросы Foundry вне Foundry. Он:
  * дополняет activities безопасными полями Midi-QOL;
  * переносит поддерживаемые настройки Midi-QOL из ``mechanics``;
  * формирует DAE-флаги для специальных длительностей;
  * проверяет исходную разметку билдера на смысловые пропуски;
  * проверяет итоговый JSON на структурные ошибки.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

import project_config

MIDI_QOL_VERSION = project_config.MIDI_QOL_VERSION
DAE_VERSION = project_config.DAE_VERSION
DND5E_VERSION = project_config.DND5E_VERSION

ACTIVITY_TYPES = {
    "attack", "save", "damage", "heal", "utility", "cast", "enchant"
}
ITEM_TYPES = {"feat", "weapon", "spell", "equipment", "consumable", "loot"}
DOCUMENT_ID = re.compile(r"^[A-Za-z0-9]{16}$")

MIDI_PROPERTIES_DEFAULTS: dict[str, Any] = {
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
}

IGNORE_TRAITS_DEFAULTS = {
    "idi": False,
    "idr": False,
    "idv": False,
    "ida": False,
    "idm": False,
}

OVER_TIME_DEFAULTS = {
    "saveRemoves": True,
    "rollAs": "target",
    "preRemoveConditionText": "",
    "postRemoveConditionText": "",
}

ATTACK_MIDI_DEFAULTS = {
    "attackMode": "oneHanded",
    "ammunition": "",
    "otherActivityUuid": "",
    "attackRollPerTarget": "default",
    "fumbleThreshold": 1,
}

DAE_DEFAULTS = {
    "selfTarget": False,
    "selfTargetAlways": False,
    "stackable": "none",
    "durationExpression": "",
    "macroRepeat": "none",
    "specialDuration": [],
    "enableCondition": "",
    "disableCondition": "",
    "disableIncapacitated": False,
    "dontApply": False,
    "showIcon": True,
}


def _ensure_mapping(
    parent: dict[str, Any],
    key: str,
    default: dict[str, Any],
    added: list[str],
) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        parent[key] = deepcopy(default)
        added.append(key)
        return parent[key]
    for child_key, child_value in default.items():
        if child_key not in value:
            value[child_key] = deepcopy(child_value)
            added.append(f"{key}.{child_key}")
    return value


def normalize_activity(activity: dict[str, Any]) -> list[str]:
    """Добавляет отсутствующие безопасные поля Midi-QOL.

    Уже существующие значения и неизвестные поля никогда не заменяются.
    Возвращает относительные пути добавленных полей.
    """
    added: list[str] = []
    simple_defaults = {
        "useConditionText": "",
        "useConditionReason": "",
        "effectConditionText": "",
        "isOverTimeFlag": False,
        "otherActivityId": "none",
        "otherActivityAsParentType": True,
    }
    for key, value in simple_defaults.items():
        if key not in activity:
            activity[key] = deepcopy(value)
            added.append(key)

    _ensure_mapping(
        activity,
        "macroData",
        {"name": "", "command": ""},
        added,
    )
    _ensure_mapping(
        activity,
        "ignoreTraits",
        IGNORE_TRAITS_DEFAULTS,
        added,
    )
    _ensure_mapping(
        activity,
        "midiProperties",
        MIDI_PROPERTIES_DEFAULTS,
        added,
    )
    _ensure_mapping(
        activity,
        "overTimeProperties",
        OVER_TIME_DEFAULTS,
        added,
    )

    if str(activity.get("type") or "").casefold() == "attack":
        for key, value in ATTACK_MIDI_DEFAULTS.items():
            if key not in activity:
                activity[key] = deepcopy(value)
                added.append(key)
    return added


def apply_activity_mechanics(
    activity: dict[str, Any],
    mechanics: dict[str, Any],
) -> None:
    """Переносит явные настройки Midi-QOL из временного ``mechanics``."""
    normalize_activity(activity)

    midi_properties = mechanics.get("midi_properties")
    if isinstance(midi_properties, dict):
        activity["midiProperties"].update(
            {
                key: deepcopy(value)
                for key, value in midi_properties.items()
                if key in MIDI_PROPERTIES_DEFAULTS
            }
        )

    text_fields = {
        "use_condition_text": "useConditionText",
        "use_condition_reason": "useConditionReason",
        "effect_condition_text": "effectConditionText",
        "other_activity_id": "otherActivityId",
    }
    for source, target in text_fields.items():
        if source in mechanics and (
            source != "other_activity_id"
            or mechanics.get(source) not in (None, "")
        ):
            activity[target] = str(mechanics.get(source) or "")

    boolean_fields = {
        "is_over_time": "isOverTimeFlag",
        "other_activity_as_parent_type": "otherActivityAsParentType",
    }
    for source, target in boolean_fields.items():
        if source in mechanics and mechanics[source] is not None:
            activity[target] = bool(mechanics[source])

    for source, target in (
        ("macro_data", "macroData"),
        ("ignore_traits", "ignoreTraits"),
        ("over_time_properties", "overTimeProperties"),
    ):
        value = mechanics.get(source)
        if isinstance(value, dict):
            activity[target].update(deepcopy(value))

    if activity.get("type") == "attack":
        if "other_activity_uuid" in mechanics:
            activity["otherActivityUuid"] = str(
                mechanics.get("other_activity_uuid") or ""
            )
        if "attack_roll_per_target" in mechanics:
            activity["attackRollPerTarget"] = str(
                mechanics.get("attack_roll_per_target") or "default"
            )
        if "fumble_threshold" in mechanics:
            try:
                activity["fumbleThreshold"] = int(
                    mechanics["fumble_threshold"]
                )
            except (TypeError, ValueError):
                pass

    if activity.get("type") == "save" and "friendly_save" in mechanics:
        activity["friendlySave"] = str(
            mechanics.get("friendly_save") or "default"
        )


def collect_effect_specs(mechanics: dict[str, Any]) -> list[Any]:
    """Собирает общие и вложенные спецификации эффектов.

    Каноническое место эффектов — ``mechanics.effects``. Для устойчивости к
    естественной ошибке генератора также принимаются ``effects`` внутри
    элемента ``mechanics.activities``. Вложенный эффект без явного селектора
    автоматически привязывается к содержащей его activity.
    """
    result: list[Any] = []
    top_level = mechanics.get("effects")
    if isinstance(top_level, list):
        result.extend(deepcopy(top_level))

    activities = mechanics.get("activities")
    if not isinstance(activities, list):
        return result

    for index, activity in enumerate(activities):
        if not isinstance(activity, dict):
            continue
        nested = activity.get("effects")
        if not isinstance(nested, list):
            continue
        selector: Any = activity.get("_id")
        if not str(selector or "").strip():
            selector = activity.get("activity_name")
        if not str(selector or "").strip():
            selector = index
        for raw_effect in nested:
            if not isinstance(raw_effect, dict):
                result.append(deepcopy(raw_effect))
                continue
            effect = deepcopy(raw_effect)
            if effect.get("activity") in (None, "") and effect.get(
                "activities"
            ) in (None, ""):
                effect["activity"] = selector
            result.append(effect)
    return result


def _plain_description(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value", "")
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _activity_chat_flavor(activity: dict[str, Any]) -> str:
    description = activity.get("description")
    if isinstance(description, dict):
        value = description.get("chatFlavor", description.get("value", ""))
        if str(value or "").strip():
            return _plain_description(value)
    return _plain_description(activity.get("chat_flavor"))


def _selector_matches_activity(
    selector: Any,
    activity: dict[str, Any],
    index: int,
) -> bool:
    if isinstance(selector, list):
        return any(
            _selector_matches_activity(value, activity, index)
            for value in selector
        )
    if isinstance(selector, (int, float)) and not isinstance(selector, bool):
        return int(selector) == index
    text = str(selector or "").casefold().strip()
    if not text:
        return index == 0
    return text in {
        str(index),
        str(activity.get("_id") or "").casefold(),
        str(activity.get("activity_name") or "").casefold(),
    }


def _source_activity_has_effect(
    mechanics: dict[str, Any],
    activity: dict[str, Any],
    index: int,
) -> bool:
    nested = activity.get("effects")
    if isinstance(nested, list) and any(
        isinstance(effect, dict) for effect in nested
    ):
        return True
    effects = mechanics.get("effects")
    if not isinstance(effects, list):
        return False
    for effect in effects:
        if not isinstance(effect, dict) or bool(effect.get("transfer", False)):
            continue
        selector = effect.get("activity", effect.get("activities"))
        if _selector_matches_activity(selector, activity, index):
            return True
    return False


def _source_weapon_base_damage(system: dict[str, Any]) -> tuple[str, str]:
    damage = system.get("damage")
    if not isinstance(damage, dict):
        return "", ""
    base = damage.get("base")
    if not isinstance(base, dict):
        return "", ""
    custom = base.get("custom")
    if isinstance(custom, dict) and custom.get("enabled"):
        formula = str(custom.get("formula") or "").strip()
    else:
        number = base.get("number")
        denomination = base.get("denomination")
        if isinstance(number, bool) or isinstance(denomination, bool):
            return "", ""
        if not isinstance(number, int) or not isinstance(denomination, int):
            return "", ""
        formula = f"{number}d{denomination}{str(base.get('bonus') or '').strip()}"
    types = base.get("types")
    damage_type = (
        str(types[0])
        if isinstance(types, list) and types
        else ""
    )
    return re.sub(r"\s+", "", formula), damage_type


def audit_source_document(document: dict[str, Any]) -> dict[str, Any]:
    """Проверяет временную разметку ``mechanics`` до её удаления билдерами."""
    errors: list[str] = []
    warnings: list[str] = []
    checked_activities = 0

    if not isinstance(document, dict):
        return {
            "activities": 0,
            "errors": ["Корень исходного JSON не является объектом."],
            "warnings": [],
        }

    raw_items = (
        document.get("items", [])
        if document.get("type") == "npc"
        else [document]
    )
    if not isinstance(raw_items, list):
        return {
            "activities": 0,
            "errors": ["$.items должен быть массивом."],
            "warnings": [],
        }

    actor_ac_calc = ""
    if document.get("type") == "npc":
        actor_system = document.get("system")
        actor_attributes = (
            actor_system.get("attributes")
            if isinstance(actor_system, dict)
            else None
        )
        actor_ac = (
            actor_attributes.get("ac")
            if isinstance(actor_attributes, dict)
            else None
        )
        if isinstance(actor_ac, dict):
            actor_ac_calc = str(actor_ac.get("calc") or "")

    for item_index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type not in ITEM_TYPES:
            continue
        item_path = "$" if item is document else f"$.items[{item_index}]"
        item_name = str(item.get("name") or f"item #{item_index + 1}")

        mechanics = item.get("mechanics")
        if not isinstance(mechanics, dict):
            continue
        activities = mechanics.get("activities")
        if not isinstance(activities, list):
            continue

        effects = mechanics.get("effects")
        if actor_ac_calc == "flat" and isinstance(effects, list):
            for effect_index, effect in enumerate(effects):
                if not isinstance(effect, dict):
                    continue
                changes = effect.get("changes")
                if not isinstance(changes, list):
                    continue
                for change_index, change in enumerate(changes):
                    if (
                        isinstance(change, dict)
                        and change.get("key") == "system.attributes.ac.bonus"
                    ):
                        errors.append(
                            f"{item_path}.mechanics.effects[{effect_index}]"
                            f".changes[{change_index}]: "
                            "system.attributes.ac.bonus не изменяет КД актёра "
                            "с calc=flat; используй "
                            "system.attributes.ac.flat либо совместимый "
                            "способ расчёта КД."
                        )

        system = item.get("system")
        system = system if isinstance(system, dict) else {}
        description = _plain_description(system.get("description")).casefold()
        uses = mechanics.get("uses")
        if not isinstance(uses, dict):
            uses = system.get("uses")
        shared_uses = (
            str(uses.get("max") or "").strip()
            if isinstance(uses, dict)
            else ""
        )

        for activity_index, activity in enumerate(activities):
            if not isinstance(activity, dict):
                errors.append(
                    f"{item_path} «{item_name}»: activity "
                    f"#{activity_index + 1} должна быть объектом."
                )
                continue
            checked_activities += 1
            activity_path = (
                f"{item_path}.mechanics.activities[{activity_index}]"
            )
            activity_type = str(activity.get("type") or "").casefold()
            activity_name = str(
                activity.get("activity_name") or ""
            ).strip()
            if not activity_name:
                errors.append(f"{activity_path}: отсутствует activity_name.")

            if activity_type == "save":
                damage = activity.get("damage")
                has_damage = isinstance(damage, list) and any(
                    isinstance(part, dict)
                    and str(part.get("formula") or "").strip()
                    for part in damage
                )
                if (
                    not has_damage
                    and not _source_activity_has_effect(
                        mechanics, activity, activity_index
                    )
                    and not _activity_chat_flavor(activity)
                ):
                    errors.append(
                        f"{activity_path}: спасбросок не содержит урона, "
                        "привязанного эффекта или полного ручного последствия "
                        "в description.chatFlavor."
                    )

            if item_type == "weapon" and activity_type == "attack":
                base_formula, base_type = _source_weapon_base_damage(system)
                if base_formula:
                    if activity.get("include_base") is False:
                        errors.append(
                            f"{activity_path}: оружейная атака с заполненным "
                            "system.damage.base не может использовать "
                            "include_base: false."
                        )
                    damage = activity.get("damage")
                    first = (
                        damage[0]
                        if isinstance(damage, list)
                        and damage
                        and isinstance(damage[0], dict)
                        else None
                    )
                    first_formula = (
                        re.sub(r"\s+", "", str(first.get("formula") or ""))
                        if isinstance(first, dict)
                        else ""
                    )
                    first_type = (
                        str(first.get("type") or "")
                        if isinstance(first, dict)
                        else ""
                    )
                    if first_formula != base_formula or (
                        base_type and first_type != base_type
                    ):
                        errors.append(
                            f"{activity_path}: первый компонент damage должен "
                            f"совпадать с system.damage.base "
                            f"({base_formula}, {base_type or 'без типа'})."
                        )

            consumption = activity.get("consumption")
            spends_item_uses = isinstance(consumption, list) and any(
                isinstance(target, dict)
                and target.get("type") == "itemUses"
                for target in consumption
            )
            if (
                item_type == "weapon"
                and len(activities) > 1
                and shared_uses
                and spends_item_uses
                and activity_name
                and activity_name.casefold() not in description
            ):
                errors.append(
                    f"{activity_path}: расходующая заряды способность "
                    f"«{activity_name}» отсутствует в полном описании оружия."
                )

        nested_count = sum(
            len(activity.get("effects", []))
            for activity in activities
            if isinstance(activity, dict)
            and isinstance(activity.get("effects"), list)
        )
        if nested_count:
            warnings.append(
                f"{item_path} «{item_name}»: {nested_count} эффект(а/ов) "
                "заданы внутри activity; билдер автоматически привяжет их, "
                "но каноническое место — mechanics.effects."
            )

    return {
        "activities": checked_activities,
        "errors": errors,
        "warnings": warnings,
    }


def effect_flags(spec: dict[str, Any]) -> dict[str, Any]:
    """Возвращает флаги эффекта с необязательной конфигурацией DAE."""
    flags = spec.get("flags")
    if isinstance(flags, dict):
        result = deepcopy(flags)
    else:
        result = {"dnd5e": {"riders": {"statuses": []}}}

    dae = spec.get("dae")
    special_duration = spec.get("special_duration")
    if isinstance(dae, dict) or special_duration not in (None, ""):
        dae_flags = result.get("dae")
        if not isinstance(dae_flags, dict):
            dae_flags = {}
            result["dae"] = dae_flags
        for key, value in DAE_DEFAULTS.items():
            dae_flags.setdefault(key, deepcopy(value))
        if isinstance(dae, dict):
            dae_flags.update(deepcopy(dae))
        if isinstance(special_duration, str):
            dae_flags["specialDuration"] = [
                value.strip()
                for value in re.split(r"[,;]+", special_duration)
                if value.strip()
            ]
        elif isinstance(special_duration, list):
            dae_flags["specialDuration"] = [
                str(value).strip()
                for value in special_duration
                if str(value).strip()
            ]
    return result


def audit_document(document: dict[str, Any]) -> dict[str, Any]:
    """Проверяет итоговый Actor/Item JSON для целевой связки версий."""
    errors: list[str] = []
    warnings: list[str] = []
    activity_count = 0
    effect_count = 0

    if not isinstance(document, dict):
        return {
            "target": _target_versions(),
            "activities": 0,
            "effects": 0,
            "errors": ["Корень документа не является JSON-объектом."],
            "warnings": [],
        }

    if document.get("type") == "npc":
        raw_items = document.get("items")
        if not isinstance(raw_items, list):
            errors.append("$.items должен быть массивом.")
            items: list[Any] = []
        else:
            items = raw_items
    elif document.get("type") in ITEM_TYPES:
        items = [document]
    else:
        items = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type not in ITEM_TYPES:
            continue
        name = str(item.get("name") or f"item #{index + 1}")
        item_path = "$" if item is document else f"$.items[{index}]"
        system = item.get("system")
        if not isinstance(system, dict):
            errors.append(f"{item_path} «{name}»: отсутствует объект system.")
            continue

        activities = system.get("activities")
        if item_type == "loot" and activities is None:
            activities = {}
        elif not isinstance(activities, dict):
            errors.append(
                f"{item_path} «{name}»: system.activities должен быть объектом."
            )
            activities = {}
        effects = item.get("effects")
        if not isinstance(effects, list):
            errors.append(f"{item_path} «{name}»: effects должен быть массивом.")
            effects = []

        effect_ids: set[str] = set()
        for effect_index, effect in enumerate(effects):
            effect_count += 1
            effect_path = f"{item_path}.effects[{effect_index}]"
            if not isinstance(effect, dict):
                errors.append(f"{effect_path} не является объектом.")
                continue
            effect_id = str(effect.get("_id") or "")
            if not DOCUMENT_ID.fullmatch(effect_id):
                errors.append(f"{effect_path}: некорректный _id «{effect_id}».")
            elif effect_id in effect_ids:
                errors.append(
                    f"{effect_path}: повторяющийся _id эффекта «{effect_id}»."
                )
            effect_ids.add(effect_id)
            if not isinstance(effect.get("statuses", []), list):
                errors.append(f"{effect_path}.statuses должен быть массивом.")
            if not isinstance(effect.get("changes", []), list):
                errors.append(f"{effect_path}.changes должен быть массивом.")
            flags = effect.get("flags", {})
            if not isinstance(flags, dict):
                errors.append(f"{effect_path}.flags должен быть объектом.")
            elif "dae" in flags:
                dae = flags["dae"]
                if not isinstance(dae, dict):
                    errors.append(f"{effect_path}.flags.dae должен быть объектом.")
                elif not isinstance(dae.get("specialDuration", []), list):
                    errors.append(
                        f"{effect_path}.flags.dae.specialDuration "
                        "должен быть массивом."
                    )

        rider_activity_ids: set[str] = set()
        rider_effect_ids: set[str] = set()
        for effect_index, effect in enumerate(effects):
            if not isinstance(effect, dict) or effect.get("type") != "enchantment":
                continue
            riders = (
                effect.get("flags", {})
                .get("dnd5e", {})
                .get("enchantment", {})
                .get("riders", {})
            )
            if not isinstance(riders, dict):
                errors.append(
                    f"{item_path}.effects[{effect_index}]: "
                    "enchantment.riders должен быть объектом."
                )
                continue
            for rider_type, destination in (
                ("activity", rider_activity_ids),
                ("effect", rider_effect_ids),
            ):
                values = riders.get(rider_type, [])
                if not isinstance(values, list):
                    errors.append(
                        f"{item_path}.effects[{effect_index}]: "
                        f"enchantment.riders.{rider_type} должен быть массивом."
                    )
                    continue
                destination.update(str(value) for value in values)
        missing_rider_activities = rider_activity_ids - set(activities)
        if missing_rider_activities:
            errors.append(
                f"{item_path} «{name}»: riders ссылаются на отсутствующие "
                "activities: "
                + ", ".join(sorted(missing_rider_activities))
                + "."
            )
        missing_rider_effects = rider_effect_ids - effect_ids
        if missing_rider_effects:
            errors.append(
                f"{item_path} «{name}»: riders ссылаются на отсутствующие "
                "effects: "
                + ", ".join(sorted(missing_rider_effects))
                + "."
            )

        referenced_effects: set[str] = set()
        for activity_key, activity in activities.items():
            activity_count += 1
            activity_path = (
                f"{item_path}.system.activities.{activity_key}"
            )
            if not isinstance(activity, dict):
                errors.append(f"{activity_path} не является объектом.")
                continue
            activity_id = str(activity.get("_id") or "")
            if not DOCUMENT_ID.fullmatch(activity_id):
                errors.append(
                    f"{activity_path}: некорректный _id «{activity_id}»."
                )
            elif activity_id != str(activity_key):
                errors.append(
                    f"{activity_path}: ключ не совпадает с _id «{activity_id}»."
                )
            activity_type = str(activity.get("type") or "").casefold()
            if activity_type not in ACTIVITY_TYPES:
                errors.append(
                    f"{activity_path}: неизвестный тип «{activity_type}»."
                )

            midi = activity.get("midiProperties")
            if not isinstance(midi, dict):
                errors.append(f"{activity_path}.midiProperties отсутствует.")
            else:
                missing = [
                    key for key in MIDI_PROPERTIES_DEFAULTS if key not in midi
                ]
                if missing:
                    errors.append(
                        f"{activity_path}.midiProperties: отсутствуют поля "
                        + ", ".join(missing)
                        + "."
                    )
                target = activity.get("target", {})
                template = (
                    target.get("template", {})
                    if isinstance(target, dict)
                    else {}
                )
                template_type = (
                    str(template.get("type") or "")
                    if isinstance(template, dict)
                    else ""
                )
                auto_target_action = str(
                    midi.get("autoTargetAction") or "default"
                )
                if (
                    template_type
                    and auto_target_action not in {"default", "none"}
                    and str(midi.get("confirmTargets") or "default")
                    == "default"
                ):
                    warnings.append(
                        f"{activity_path}: шаблон подсвечивает цели, но "
                        "confirmTargets наследуется из мира; список целей "
                        "activity может остаться пустым."
                    )

            for key in (
                "useConditionText",
                "useConditionReason",
                "effectConditionText",
                "isOverTimeFlag",
                "overTimeProperties",
            ):
                if key not in activity:
                    errors.append(f"{activity_path}: отсутствует поле {key}.")

            if activity_type == "attack":
                for key in ATTACK_MIDI_DEFAULTS:
                    if key not in activity:
                        errors.append(
                            f"{activity_path}: у attack отсутствует поле {key}."
                        )
                if not isinstance(activity.get("attack"), dict):
                    errors.append(f"{activity_path}.attack должен быть объектом.")
                damage = activity.get("damage")
                if not isinstance(damage, dict):
                    errors.append(f"{activity_path}.damage должен быть объектом.")
                else:
                    parts = damage.get("parts")
                    if not isinstance(parts, list):
                        errors.append(
                            f"{activity_path}.damage.parts должен быть массивом."
                        )
                        parts = []
                    include_base = bool(damage.get("includeBase", False))
                    item_damage = system.get("damage")
                    base = (
                        item_damage.get("base")
                        if isinstance(item_damage, dict)
                        else None
                    )
                    has_base_damage = bool(
                        isinstance(base, dict)
                        and (
                            (
                                base.get("number") not in (None, "")
                                and base.get("denomination") not in (None, "", 0)
                            )
                            or (
                                isinstance(base.get("custom"), dict)
                                and bool(base["custom"].get("enabled"))
                                and str(
                                    base["custom"].get("formula") or ""
                                ).strip()
                            )
                        )
                    )
                    has_activity_damage = any(
                        isinstance(part, dict)
                        and (
                            (
                                part.get("number") not in (None, "")
                                and part.get("denomination")
                                not in (None, "", 0)
                            )
                            or (
                                isinstance(part.get("custom"), dict)
                                and bool(part["custom"].get("enabled"))
                                and str(
                                    part["custom"].get("formula") or ""
                                ).strip()
                            )
                        )
                        for part in parts
                    )
                    rider_uses_target_base = (
                        activity_id in rider_activity_ids
                        and include_base
                    )
                    if not has_activity_damage and not (
                        include_base and has_base_damage
                    ) and not rider_uses_target_base:
                        errors.append(
                            f"{activity_path}: атака не имеет эффективного "
                            "урона для кнопки броска."
                        )
                    if item_type == "weapon" and not include_base:
                        errors.append(
                            f"{activity_path}: оружейная атака должна "
                            "использовать system.damage.base через "
                            "damage.includeBase=true."
                        )
                    if (
                        item_type == "weapon"
                        and include_base
                        and not has_base_damage
                    ):
                        errors.append(
                            f"{activity_path}: includeBase=true, но "
                            "system.damage.base не содержит формулу урона."
                        )
            elif activity_type == "save":
                if not isinstance(activity.get("save"), dict):
                    errors.append(f"{activity_path}.save должен быть объектом.")
            elif activity_type == "heal":
                if not isinstance(activity.get("healing"), dict):
                    errors.append(f"{activity_path}.healing должен быть объектом.")
            elif activity_type == "cast":
                spell = activity.get("spell")
                if not isinstance(spell, dict):
                    errors.append(f"{activity_path}.spell должен быть объектом.")
                elif not str(spell.get("uuid") or "").strip():
                    errors.append(
                        f"{activity_path}.spell.uuid не должен быть пустым."
                    )
            elif activity_type in {"damage", "save"}:
                if not isinstance(activity.get("damage"), dict):
                    errors.append(f"{activity_path}.damage должен быть объектом.")

            consumption = activity.get("consumption")
            if not isinstance(consumption, dict):
                errors.append(f"{activity_path}.consumption должен быть объектом.")
            else:
                targets = consumption.get("targets", [])
                if not isinstance(targets, list):
                    errors.append(
                        f"{activity_path}.consumption.targets должен быть массивом."
                    )
                else:
                    for target_index, target in enumerate(targets):
                        if not isinstance(target, dict) or not target.get("type"):
                            errors.append(
                                f"{activity_path}.consumption.targets"
                                f"[{target_index}] некорректен."
                            )

            references = activity.get("effects", [])
            if not isinstance(references, list):
                errors.append(f"{activity_path}.effects должен быть массивом.")
            else:
                for reference_index, reference in enumerate(references):
                    if not isinstance(reference, dict):
                        errors.append(
                            f"{activity_path}.effects[{reference_index}] "
                            "не является объектом."
                        )
                        continue
                    reference_id = str(reference.get("_id") or "")
                    referenced_effects.add(reference_id)
                    if reference_id not in effect_ids:
                        errors.append(
                            f"{activity_path}: ссылка на отсутствующий эффект "
                            f"«{reference_id}»."
                        )

        for effect_index, effect in enumerate(effects):
            if not isinstance(effect, dict):
                continue
            effect_id = str(effect.get("_id") or "")
            transfer = bool(effect.get("transfer", False))
            if (
                effect.get("type") != "enchantment"
                and transfer
                and effect_id in referenced_effects
            ):
                warnings.append(
                    f"{item_path} «{name}»: transfer-эффект «{effect_id}» "
                    "одновременно привязан к activity."
                )
            if not transfer and effect_id not in referenced_effects:
                warnings.append(
                    f"{item_path} «{name}»: применяемый эффект «{effect_id}» "
                    "не привязан ни к одной activity."
                )

    return {
        "target": _target_versions(),
        "activities": activity_count,
        "effects": effect_count,
        "errors": errors,
        "warnings": warnings,
    }


def _target_versions() -> dict[str, str]:
    return {
        "dnd5e": DND5E_VERSION,
        "midi-qol": MIDI_QOL_VERSION,
        "dae": DAE_VERSION,
    }
