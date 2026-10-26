#!/usr/bin/env python3
"""Проверка целостности канонического проекта и системы усилений."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import builder_app
import build_enhancement_module
import enhancement_builder
import enhancement_policy
import enhancement_set_builder
import equipment_builder
import midi_compat
import project_config
import rolltable_builder


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "PROJECT_MANIFEST.json"
NUMBERED_COPY = re.compile(r"\(\d+\)(?=\.[^.]+$)")
TEMPLATE_KEYS = {
    "npc",
    "feat",
    "weapon",
    "equipment",
    "spell",
    "consumable",
    "item",
    "enhancement",
    "enhancement_set",
}
LEGACY_TEMPLATE_FILES = {
    f"{template_key}_template.json"
    for template_key in TEMPLATE_KEYS
}
DOCUMENTATION_FILES = {
    "AI_FOUNDRY_BUILDER_GUIDE.md",
    "docs/COMMON_JSON.md",
    "docs/CONSUMABLES_JSON.md",
    "docs/CONTENT_DESIGN.md",
    "docs/EQUIPMENT_JSON.md",
    "docs/ENHANCEMENTS_JSON.md",
    "docs/ENHANCEMENTS_README.md",
    "docs/FEATURES_JSON.md",
    "docs/ITEM_ENHANCEMENT_POLICY.md",
    "docs/ITEMS_JSON.md",
    "docs/NPC_JSON.md",
    "docs/PROJECT_MAINTENANCE.md",
    "docs/SPELLS_JSON.md",
    "docs/VALIDATION.md",
    "docs/WEAPONS_JSON.md",
}
REQUIRED_GUIDE_MARKERS = {
    "AI_FOUNDRY_BUILDER_GUIDE.md": (
        "единственная обязательная точка входа",
        "docs/CONTENT_DESIGN.md",
        "docs/COMMON_JSON.md",
        "docs/NPC_JSON.md",
        "docs/WEAPONS_JSON.md",
        "docs/EQUIPMENT_JSON.md",
        "docs/SPELLS_JSON.md",
        "docs/FEATURES_JSON.md",
        "docs/CONSUMABLES_JSON.md",
        "docs/ITEMS_JSON.md",
        "docs/ITEM_ENHANCEMENT_POLICY.md",
        "docs/ENHANCEMENTS_JSON.md",
        "docs/VALIDATION.md",
        "docs/PROJECT_MAINTENANCE.md",
        "package_project.py",
    ),
    "COMMON_JSON.md": (
        "builder_app.py",
        "system.activities",
        "mechanics",
    ),
    "CONTENT_DESIGN.md": (
        "творческая проверка",
        "JSON-проверка",
        "builder_app.py",
    ),
    "ITEM_ENHANCEMENT_POLICY.md": (
        "open",
        "restricted",
        "locked",
        "material_property",
        "ENHANCEMENTS_JSON.md",
    ),
    "ENHANCEMENTS_JSON.md": (
        "Перед выдачей JSON пользователю в чате",
        "builder_app.py",
        "docs/CONTENT_DESIGN.md",
    ),
    "VALIDATION.md": (
        "Перед выдачей JSON пользователю в чате",
        "builder_app.py",
    ),
    "PROJECT_MAINTENANCE.md": (
        "canonical_files",
        "package_project.py",
        "побайтово",
    ),
}
ABSOLUTE_WORKSPACE_PATH = re.compile(r"(?:[A-Za-z]:\\|/workspace/|/tmp/)")
JSON_FENCE = re.compile(r"```json\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
LEGACY_RANDOM_FILES = {
    "random_upgrade.py",
    "build_random_upgrade_module.py",
    "RANDOM_UPGRADES_README.md",
    "random-upgrade-runtime.mjs",
    "runtime/foundry-json-builder-random-upgrades/module.json",
    (
        "runtime/foundry-json-builder-random-upgrades/scripts/"
        "random-upgrade-runtime.mjs"
    ),
}
LEGACY_PROJECT_FILES = {
    "AI_CONTENT_DESIGN_GUIDE.md",
    "AI_ENHANCEMENT_JSON_GUIDE.md",
    "AI_NPC_JSON_GUIDE.md",
    "ENHANCEMENTS_README.md",
    "fvtt-midi-qol-settings.json",
    "korol_lich_artas_npc_3.json",
}


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def _audit_markdown_json(path: Path, errors: list[str]) -> None:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        errors.append(f"Не удалось прочитать руководство {path.name}: {error}")
        return
    for index, block in enumerate(JSON_FENCE.findall(text), start=1):
        try:
            json.loads(block)
        except json.JSONDecodeError as error:
            errors.append(
                f"{path.name}: JSON-пример #{index} некорректен, "
                f"строка {error.lineno}: {error.msg}."
            )
    folded_text = text.casefold()
    for marker in REQUIRED_GUIDE_MARKERS.get(path.name, ()):
        if marker.casefold() not in folded_text:
            errors.append(
                f"{path.name} не содержит обязательный пункт: {marker}."
            )


def _audit_target_versions(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        core = value.get("coreVersion")
        system = value.get("systemVersion")
        if core not in (None, "") and str(core) != project_config.EXPORT_CORE_VERSION:
            errors.append(
                f"{path}.coreVersion={core}, ожидалось "
                f"{project_config.EXPORT_CORE_VERSION}."
            )
        if system not in (None, "") and str(system) != project_config.DND5E_VERSION:
            errors.append(
                f"{path}.systemVersion={system}, ожидалось "
                f"{project_config.DND5E_VERSION}."
            )
        for key, child in value.items():
            _audit_target_versions(child, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _audit_target_versions(child, f"{path}[{index}]", errors)


def _audit_export_core_compatibility(errors: list[str]) -> None:
    sample = {
        "_stats": {"coreVersion": "13.999"},
        "items": [
            {"_stats": {"coreVersion": "13.999"}},
            {"effects": [{"_stats": {"coreVersion": "13.999"}}]},
        ],
    }
    project_config.normalize_export_versions(sample)
    found: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            stats = value.get("_stats")
            if isinstance(stats, dict) and "coreVersion" in stats:
                found.append(str(stats["coreVersion"]))
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(sample)
    if not found or any(
        version != project_config.EXPORT_CORE_VERSION for version in found
    ):
        errors.append(
            "Нормализация export_core не переписала все вложенные документы."
        )

    try:
        templates = _load_json(ROOT / "templates.json")
        source = deepcopy(templates["templates"]["weapon"])
        source.setdefault("_stats", {})["coreVersion"] = "13.999"
        outcome = builder_app.build_document(
            "weapon", source, source_name="contract:export_core"
        )
    except Exception as error:
        errors.append(f"Контракт export_core завершился ошибкой: {error}")
        return
    actual = str(outcome.document.get("_stats", {}).get("coreVersion") or "")
    if actual != project_config.EXPORT_CORE_VERSION:
        errors.append(
            "builder_app не заменил более новую coreVersion на export_core."
        )


def _audit_source_example(
    path: Path,
    source: dict[str, Any],
    errors: list[str],
) -> None:
    builder_key = builder_app.detect_builder(source)
    if not builder_key:
        return
    try:
        once = builder_app.build_document(
            builder_key,
            source,
            source_name=path.name,
        )
        repeat_source = source if builder_key == "enhancement" else once.document
        twice = builder_app.build_document(
            builder_key,
            repeat_source,
            source_name=f"{path.name}: повторный прогон",
        )
    except Exception as error:
        errors.append(f"JSON-пример {path.name} не проходит builder_app: {error}")
        return
    if once.document != twice.document:
        errors.append(
            f"JSON-пример {path.name} изменяется при повторном прогоне builder_app."
        )


def _audit_runtime_script(errors: list[str]) -> None:
    script = (
        ROOT
        / "runtime"
        / enhancement_builder.MODULE_ID
        / "scripts"
        / "enhancement-groups.mjs"
    )
    if not script.is_file():
        errors.append(f"Отсутствует runtime-контроллер: {script.relative_to(ROOT)}")
        return
    try:
        text = script.read_text(encoding="utf-8-sig")
    except OSError as error:
        errors.append(f"Не удалось прочитать runtime-контроллер: {error}")
        return
    if "random_upgrade" in text or "random-upgrade" in text:
        errors.append("Runtime-контроллер содержит остатки random_upgrade.")
    required_attunement_tokens = {
        "ATTUNEMENT_THRESHOLD",
        "GROUP_ALIASES",
        "occupiedGroups",
        'primaryGroup === "signature_property"',
        "targetMismatch",
        "itemPolicy",
        "policyMismatch",
        '"material_property"',
        'mode === "locked"',
        "policy.reservedGroups",
        "policy.allowedGroups",
        "enforceTargetRestrictions",
        "reconcileAttunement",
        "queueAttunementReconcile",
        "preserveManualAttunement",
        'Hooks.on("updateActiveEffect"',
        'Hooks.on("updateItem"',
        'Hooks.on("preCreateActiveEffect"',
        '"system.attunement": "required"',
        '"elemental_damage", "additional_damage"',
    }
    missing_attunement_tokens = sorted(
        token for token in required_attunement_tokens if token not in text
    )
    if missing_attunement_tokens:
        errors.append(
            "Runtime-контроллер не содержит полный контракт автоматической "
            "настройки: "
            + ", ".join(missing_attunement_tokens)
            + "."
        )
    node = shutil.which("node")
    if node:
        completed = subprocess.run(
            [node, "--check", str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            errors.append(
                "Runtime-контроллер не прошёл node --check: "
                + (completed.stderr or completed.stdout).strip()
            )


def _audit_builder_contracts(errors: list[str]) -> None:
    """Проверяет ветви, которые пустые канонические шаблоны не затрагивают."""
    cases: list[tuple[str, dict[str, Any], set[str]]] = []

    feat = equipment_builder.load_template("feat")
    feat["name"] = "Контрольная атака особенности"
    feat["system"]["description"]["value"] = (
        "<p>Дальнобойная атака заклинанием: +7 к попаданию, 60 футов. "
        "Попадание: 2d8 урона силовым полем.</p>"
    )
    feat["mechanics"] = {
        "activities": [
            {
                "type": "attack",
                "activity_name": "Контрольная атака",
                "attack": {
                    "ability": "none",
                    "bonus": "+7",
                    "flat": True,
                    "type": "ranged",
                    "classification": "spell",
                },
                "damage": [{"formula": "2d8", "type": "force"}],
                "targeting": {
                    "range": {"value": 60, "units": "ft"},
                    "affects": {
                        "count": 1,
                        "type": "creature",
                        "choice": True,
                    },
                },
                "activation": {"type": "action", "value": 1},
            }
        ]
    }
    cases.append(("feat", feat, {"attack"}))

    spell = equipment_builder.load_template("spell")
    spell["name"] = "Контрольное заклинание"
    spell["system"]["description"]["value"] = (
        "<p>Совершите дальнобойную атаку заклинанием. При попадании цель "
        "получает 2d6 урона огнём. Вторая кнопка восстанавливает 1d6 хитов.</p>"
    )
    spell["mechanics"] = {
        "activities": [
            {
                "type": "attack",
                "activity_name": "Огненный луч",
                "attack": {
                    "ability": "spellcasting",
                    "bonus": "",
                    "flat": False,
                    "type": "ranged",
                    "classification": "spell",
                },
                "damage": [{"formula": "2d6", "type": "fire"}],
                "targeting": {
                    "range": {"value": 60, "units": "ft"},
                    "affects": {
                        "count": 1,
                        "type": "creature",
                        "choice": True,
                    },
                },
                "activation": {"type": "action", "value": 1},
            },
            {
                "type": "heal",
                "activity_name": "Восстановление",
                "healing": {"formula": "1d6", "type": "healing"},
                "targeting": {
                    "range": {"units": "self"},
                    "affects": {"type": "self"},
                },
                "activation": {"type": "special", "value": None},
            },
        ]
    }
    cases.append(("spell", spell, {"attack", "heal"}))

    consumable = equipment_builder.load_template("consumable")
    consumable["name"] = "Контрольное зелье"
    consumable["system"]["description"]["value"] = (
        "<p>Восстанавливает 2d4 + 2 хита.</p>"
    )
    consumable["mechanics"] = {
        "activities": [
            {
                "type": "heal",
                "activity_name": "Выпить",
                "healing": {"formula": "2d4+2", "type": "healing"},
                "targeting": {
                    "range": {"units": "self"},
                    "affects": {"type": "self"},
                },
                "activation": {"type": "action", "value": 1},
            }
        ],
        "uses": {"max": "1", "spent": 0, "autoDestroy": True},
    }
    cases.append(("consumable", consumable, {"heal"}))

    equipment = equipment_builder.load_template("equipment")
    equipment["name"] = "Контрольный жезл"
    equipment["system"]["description"]["value"] = (
        "<p>Жезл накладывает контрольное заклинание действием.</p>"
    )
    equipment["mechanics"] = {
        "activities": [
            {
                "type": "cast",
                "activity_name": "Наложить заклинание",
                "spell": {
                    "uuid": "Compendium.dnd5e.spells.Item.L4J89JXqbKs6puEV",
                    "level": 1,
                    "challenge": {
                        "attack": None,
                        "save": None,
                        "override": False,
                    },
                    "properties": [],
                },
                "activation": {"type": "action", "value": 1},
            }
        ]
    }
    cases.append(("equipment", equipment, {"cast"}))

    weapon = equipment_builder.load_template("weapon")
    weapon["name"] = "Контрольное оружие NPC"
    weapon["system"]["damage"]["base"] = {
        "number": None,
        "denomination": None,
        "bonus": "",
        "types": ["slashing"],
        "custom": {"enabled": True, "formula": "1d8+7"},
        "scaling": {"mode": "", "number": None, "formula": ""},
    }
    weapon["mechanics"] = {
        "activities": [
            {
                "type": "attack",
                "activity_name": "Контрольный удар",
                "attack": {
                    "ability": "none",
                    "bonus": "+13",
                    "flat": True,
                    "type": "melee",
                    "classification": "weapon",
                },
                "damage": [
                    {"formula": "1d8+7", "type": "slashing"},
                    {"formula": "2d8", "type": "force"},
                ],
                "include_base": True,
                "range": {
                    "reach": 5,
                    "units": "ft",
                    "count": 1,
                    "target_type": "creature",
                },
                "activation": {"type": "action", "value": 1},
            }
        ]
    }
    cases.append(("weapon", weapon, {"attack"}))

    for builder_key, source, expected_types in cases:
        try:
            outcome = builder_app.build_document(
                builder_key,
                deepcopy(source),
                source_name=f"contract:{builder_key}",
            )
        except Exception as error:
            errors.append(
                f"Контрактный тест {builder_key} завершился ошибкой: {error}"
            )
            continue
        activities = outcome.document.get("system", {}).get("activities", {})
        actual_types = {
            str(activity.get("type") or "")
            for activity in activities.values()
            if isinstance(activity, dict)
        }
        if not expected_types.issubset(actual_types):
            errors.append(
                f"Контрактный тест {builder_key} ожидал activities "
                f"{sorted(expected_types)}, получил {sorted(actual_types)}."
            )
        if builder_key == "weapon":
            base = outcome.document.get("system", {}).get("damage", {}).get("base", {})
            if str(base.get("bonus") or "") != "+7":
                errors.append(
                    "Контрактный тест weapon потерял фиксированный бонус +7 "
                    "при переносе первого компонента в system.damage.base."
                )
            attack_activities = [
                activity
                for activity in activities.values()
                if isinstance(activity, dict) and activity.get("type") == "attack"
            ]
            if (
                not attack_activities
                or attack_activities[0].get("damage", {}).get("includeBase")
                is not True
            ):
                errors.append(
                    "Контрактный тест weapon не использует базовый урон оружия."
                )

    material_weapon = equipment_builder.load_template("weapon")
    material_weapon["name"] = "Клинок из звёздной стали"
    material_weapon["enhancement_policy"] = {
        "mode": "restricted",
        "allowed_groups": ["utility_property"],
        "native_properties": [
            {
                "group": "additional_damage",
                "name": "Звёздное пламя",
                "description": "Врождённый дополнительный урон клинка.",
            }
        ],
        "material_property": {
            "id": "starsteel",
            "name": "Звёздная сталь",
            "benefits": [
                "Оружие считается серебряным.",
                "Клинок светится рядом с существами из Отголосков.",
            ],
        },
        "reason": "Материал допускает только утилитарные руны.",
    }
    try:
        material_result = builder_app.build_document(
            "weapon",
            material_weapon,
            source_name="contract:material_property",
        ).document
    except Exception as error:
        errors.append(f"Контракт material_property завершился ошибкой: {error}")
    else:
        policy = (
            material_result.get("flags", {})
            .get(enhancement_policy.MODULE_ID, {})
            .get("itemPolicy", {})
        )
        if (
            policy.get("mode") != "restricted"
            or policy.get("reservedGroups") != ["additional_damage"]
            or policy.get("allowedGroups") != ["utility_property"]
            or policy.get("materialProperty", {}).get("group")
            != "material_property"
            or policy.get("materialProperty", {}).get("id") != "starsteel"
            or "enhancement_policy" in material_result
        ):
            errors.append(
                "Контракт material_property неверно скомпилировал политику "
                "предмета."
            )

    legacy_artifact = equipment_builder.load_template("weapon")
    legacy_artifact["name"] = "Старый артефакт"
    legacy_artifact["system"]["rarity"] = "artifact"
    legacy_artifact.pop("enhancement_policy", None)
    try:
        artifact_result = builder_app.build_document(
            "weapon",
            legacy_artifact,
            source_name="contract:legacy_artifact",
        ).document
    except Exception as error:
        errors.append(
            f"Контракт безопасного артефакта завершился ошибкой: {error}"
        )
    else:
        policy = (
            artifact_result.get("flags", {})
            .get(enhancement_policy.MODULE_ID, {})
            .get("itemPolicy", {})
        )
        if policy.get("mode") != "locked" or not policy.get("reason"):
            errors.append(
                "Артефакт без явной политики не был автоматически закрыт."
            )

    invalid_policy = {
        "mode": "open",
        "allowed_groups": [],
        "native_properties": [
            {
                "group": "defensive_property",
                "name": "Первая защита",
                "description": "Первое врождённое свойство.",
            },
            {
                "group": "defensive_property",
                "name": "Вторая защита",
                "description": "Второе врождённое свойство.",
            },
        ],
        "material_property": None,
        "reason": "",
    }
    try:
        enhancement_policy.validate_policy(invalid_policy)
    except enhancement_policy.EnhancementPolicyError:
        pass
    else:
        errors.append(
            "Валидатор политики принял две записи одной врождённой группы."
        )

    incompatible_ac = equipment_builder.load_template("npc")
    incompatible_ac["name"] = "Контроль несовместимой КД"
    incompatible_ac["system"]["attributes"]["ac"] = {
        "calc": "flat",
        "flat": 21,
        "formula": "",
    }
    ac_feat = equipment_builder.load_template("feat")
    ac_feat["name"] = "Несовместимый бонус КД"
    ac_feat["mechanics"] = {
        "activities": [
            {
                "type": "utility",
                "activity_name": "Активировать защиту",
                "activation": {"type": "bonus", "value": 1},
            }
        ],
        "effects": [
            {
                "name": "Бонус КД",
                "activity": "Активировать защиту",
                "changes": [
                    {
                        "key": "system.attributes.ac.bonus",
                        "mode": "add",
                        "value": "2",
                    }
                ],
            }
        ],
    }
    incompatible_ac["items"] = [ac_feat]
    ac_contract = midi_compat.audit_source_document(incompatible_ac)
    if not any(
        "system.attributes.ac.bonus не изменяет КД" in issue
        for issue in ac_contract["errors"]
    ):
        errors.append(
            "Исходный валидатор не обнаружил ac.bonus при calc=flat."
        )


def _manifest_files(manifest: dict[str, Any]) -> list[str]:
    groups = manifest.get("canonical_files")
    if not isinstance(groups, dict):
        return []
    return [
        str(filename)
        for filenames in groups.values()
        if isinstance(filenames, list)
        for filename in filenames
    ]


def _has_built_activities(document: Any) -> bool:
    if not isinstance(document, dict):
        return False
    candidates = (
        document.get("items", [])
        if document.get("type") == "npc"
        else [document]
    )
    return isinstance(candidates, list) and any(
        isinstance(item, dict)
        and isinstance((item.get("system") or {}).get("activities"), dict)
        and bool((item.get("system") or {}).get("activities"))
        for item in candidates
    )


def _audit_enhancement_documents(errors: list[str]) -> None:
    try:
        source = _load_json(ROOT / "enhancement_test_set.json")
        validated = enhancement_set_builder.validate_set(source)
        documents, report = enhancement_set_builder.build_set_documents(source)
    except Exception as error:
        errors.append(f"Сборка тестового набора усилений завершилась ошибкой: {error}")
        return

    if report["packs"] != {
        enhancement_set_builder.ENHANCERS_PACK: 8,
        enhancement_set_builder.CATALOG_PACK: 17,
        enhancement_set_builder.TABLES_PACK: 8,
    }:
        errors.append("Тестовый набор создал неверное количество документов.")

    enhancers = documents[enhancement_set_builder.ENHANCERS_PACK]
    for enhancer_index, candidate in enumerate(enhancers):
        compatibility = midi_compat.audit_document(candidate)
        errors.extend(
            f"Тестовый усилитель #{enhancer_index + 1}: {issue}"
            for issue in compatibility["errors"]
        )
    enhancer = enhancers[0]
    activities = enhancer.get("system", {}).get("activities", {})
    enchant_activities = [
        activity
        for activity in activities.values()
        if isinstance(activity, dict) and activity.get("type") == "enchant"
    ]
    if len(enchant_activities) != 1:
        errors.append("Усилитель должен содержать ровно одну activity Enchant.")
        return
    activity = enchant_activities[0]
    effect_ids = {
        effect.get("_id")
        for effect in enhancer.get("effects", [])
        if isinstance(effect, dict) and effect.get("type") == "enchantment"
    }
    profile_ids = {
        profile.get("_id")
        for profile in activity.get("effects", [])
        if isinstance(profile, dict)
    }
    if effect_ids != profile_ids or len(effect_ids) != 3:
        errors.append("Профили Enchant не совпадают с тремя Enchantment-эффектами.")
    if activity.get("appliedEffects") != [
        effect["_id"]
        for effect in enhancer["effects"]
        if effect.get("type") == "enchantment"
    ]:
        errors.append("appliedEffects не совпадает с порядком профилей.")
    consumption = activity.get("consumption", {}).get("targets", [])
    if not any(
        isinstance(target, dict)
        and target.get("type") == "itemUses"
        and str(target.get("value")) == "1"
        for target in consumption
    ):
        errors.append("Enchant не расходует одно использование усилителя.")
    for effect in enhancer["effects"]:
        if effect.get("type") != "enchantment":
            continue
        metadata = (
            effect.get("flags", {})
            .get(enhancement_builder.MODULE_ID, {})
            .get("enhancement")
        )
        if not isinstance(metadata, dict) or not {
            "id", "group", "tier", "rank", "occupiesGroups", "setId",
            "attunement", "target"
        }.issubset(metadata):
            errors.append(
                "Enchantment не содержит полные метаданные схемы 5."
            )

    expected_rider_scenarios = {
        "active_self_test_t1": ("utility", False),
        "active_target_test_t1": ("save", False),
        "passive_self_test_t1": (None, True),
        "passive_target_test_t1": ("attack", False),
    }
    seen_scenarios: set[str] = set()
    expected_bundles = {
        "primal_flame_bundle_t3": {
            "groups": {
                "numeric_bonus",
                "additional_damage",
                "defensive_property",
                "active_power",
            },
            "secondary": 3,
            "target": "weapon",
        },
        "storm_colossus_bundle_t3": {
            "groups": {
                "numeric_bonus",
                "defensive_property",
                "active_power",
            },
            "secondary": 2,
            "target": "equipment",
            "system_types": {
                "light", "medium", "heavy", "natural", "shield"
            },
        },
    }
    signature_pool_id = "stormborn_heart_t3_pool"
    signature_seen = False
    bundle_candidates: dict[str, dict[str, Any]] = {}
    for candidate in enhancers[1:]:
        pool_id = str(
            candidate.get("flags", {})
            .get(enhancement_builder.MODULE_ID, {})
            .get("enhancer", {})
            .get("poolId")
            or ""
        )
        if pool_id in expected_bundles:
            bundle_candidates[pool_id] = candidate
            continue
        if pool_id == signature_pool_id:
            signature_seen = True
            candidate_activities = candidate.get("system", {}).get(
                "activities", {}
            )
            discharge = [
                value
                for value in candidate_activities.values()
                if isinstance(value, dict)
                and value.get("name") == "Обратный разряд"
            ]
            if len(discharge) != 1:
                errors.append(
                    "Уникальное усиление не создало «Обратный разряд»."
                )
                continue
            activity = discharge[0]
            if (
                activity.get("activation", {}).get("type") != "reaction"
                or activity.get("uses", {}).get("max") != "2"
                or activity.get("consumption", {}).get("targets", [{}])[0].get(
                    "type"
                )
                != "activityUses"
            ):
                errors.append(
                    "«Обратный разряд» неверно хранит реакцию или заряды."
                )
            signature_effects = [
                effect
                for effect in candidate.get("effects", [])
                if isinstance(effect, dict)
                and effect.get("type") == "enchantment"
            ]
            if len(signature_effects) != 1:
                errors.append(
                    "Уникальное усиление должно содержать один Enchantment."
                )
                continue
            metadata = (
                signature_effects[0]
                .get("flags", {})
                .get(enhancement_builder.MODULE_ID, {})
                .get("enhancement", {})
            )
            if metadata.get("occupiesGroups") != [
                "signature_property",
            ]:
                errors.append(
                    "Уникальное усиление блокирует обычные группы вместо "
                    "отдельного слота signature_property."
                )
            if metadata.get("signatureBenefits") != [
                "Постоянное сопротивление урону электричеством",
                "Реактивный обратный разряд накопленной энергии",
            ]:
                errors.append(
                    "Уникальное усиление потеряло перечень особых эффектов."
                )
            if metadata.get("attunement") != {
                "weight": 4,
                "required": True,
            }:
                errors.append(
                    "Уникальное усиление неверно требует настройку."
                )
            continue
        if pool_id not in expected_rider_scenarios:
            errors.append(f"Неизвестный тестовый rider-пул: {pool_id or 'пусто'}.")
            continue
        seen_scenarios.add(pool_id)
        expected_activity_type, expected_transfer = expected_rider_scenarios[pool_id]
        candidate_activities = candidate.get("system", {}).get("activities", {})
        rider_activities = [
            value
            for value in candidate_activities.values()
            if isinstance(value, dict) and value.get("type") != "enchant"
        ]
        actual_activity_types = {
            str(value.get("type") or "") for value in rider_activities
        }
        if expected_activity_type is None:
            if rider_activities:
                errors.append(
                    f"{pool_id}: постоянный self-rider создал лишнюю activity."
                )
        elif actual_activity_types != {expected_activity_type}:
            errors.append(
                f"{pool_id}: ожидалась rider activity "
                f"{expected_activity_type}, получено {sorted(actual_activity_types)}."
            )

        profile_effects = [
            effect
            for effect in candidate.get("effects", [])
            if isinstance(effect, dict) and effect.get("type") == "enchantment"
        ]
        base_effects = [
            effect
            for effect in candidate.get("effects", [])
            if isinstance(effect, dict) and effect.get("type") == "base"
        ]
        if len(profile_effects) != 1 or len(base_effects) != 1:
            errors.append(
                f"{pool_id}: ожидался один Enchantment и один rider Active Effect."
            )
            continue
        rider_effect = base_effects[0]
        if bool(rider_effect.get("transfer")) is not expected_transfer:
            errors.append(f"{pool_id}: неверное значение transfer rider-эффекта.")
        riders = (
            profile_effects[0]
            .get("flags", {})
            .get("dnd5e", {})
            .get("enchantment", {})
            .get("riders", {})
        )
        if riders.get("effect") != [rider_effect["_id"]]:
            errors.append(f"{pool_id}: профиль потерял ссылку на rider-эффект.")
        expected_activity_ids = [
            activity["_id"] for activity in rider_activities
        ]
        if riders.get("activity") != expected_activity_ids:
            errors.append(f"{pool_id}: профиль потерял ссылки на rider activities.")
        if not expected_transfer:
            if not any(
                rider_effect["_id"]
                in {
                    reference.get("_id")
                    for reference in activity.get("effects", [])
                    if isinstance(reference, dict)
                }
                for activity in rider_activities
            ):
                errors.append(
                    f"{pool_id}: применяемый rider-эффект не привязан к activity."
                )
    if not signature_seen:
        errors.append("Не найден проверочный пул уникального усиления.")
    if seen_scenarios != set(expected_rider_scenarios):
        errors.append("Тестовый набор не содержит все четыре rider-сценария.")

    if set(bundle_candidates) != set(expected_bundles):
        errors.append("Тестовый набор не содержит оба составных усилителя.")
    for pool_id, expectations in expected_bundles.items():
        bundle_candidate = bundle_candidates.get(pool_id)
        if bundle_candidate is None:
            continue
        bundle_profiles = [
            effect
            for effect in bundle_candidate.get("effects", [])
            if isinstance(effect, dict) and effect.get("type") == "enchantment"
        ]
        if len(bundle_profiles) != 1:
            errors.append(
                f"{pool_id}: составной усилитель должен содержать один "
                "выбираемый профиль."
            )
            continue

        enchant_activities = [
            activity
            for activity in bundle_candidate.get("system", {})
            .get("activities", {})
            .values()
            if isinstance(activity, dict) and activity.get("type") == "enchant"
        ]
        restrictions = (
            enchant_activities[0].get("restrictions", {})
            if len(enchant_activities) == 1
            else {}
        )
        if restrictions.get("type") != expectations["target"]:
            errors.append(
                f"{pool_id}: Enchant имеет неверный тип цели."
            )

        primary_metadata = (
            bundle_profiles[0]
            .get("flags", {})
            .get(enhancement_builder.MODULE_ID, {})
            .get("enhancement", {})
        )
        bundle_metadata = primary_metadata.get("bundle", {})
        components = bundle_metadata.get("components", [])
        if len(components) != expectations["secondary"]:
            errors.append(
                f"{pool_id}: составной профиль содержит неверное число "
                "вторичных компонентов."
            )
        component_metadata = [
            component.get("effect", {})
            .get("flags", {})
            .get(enhancement_builder.MODULE_ID, {})
            .get("enhancement", {})
            for component in components
            if isinstance(component, dict)
        ]
        component_groups = {
            metadata.get("group")
            for metadata in component_metadata
            if isinstance(metadata, dict)
        }
        if component_groups | {primary_metadata.get("group")} != expectations["groups"]:
            errors.append(
                f"{pool_id}: составной профиль занимает неверные группы."
            )

        all_metadata = [primary_metadata, *component_metadata]
        for metadata in all_metadata:
            if not isinstance(metadata, dict):
                continue
            if metadata.get("rank") != "standard":
                errors.append(f"{pool_id}: компонент потерял ранг standard.")
            if metadata.get("occupiesGroups") != [metadata.get("group")]:
                errors.append(
                    f"{pool_id}: обычный компонент занимает неверные группы."
                )
            if metadata.get("target", {}).get("itemTypes") != [
                expectations["target"]
            ]:
                errors.append(
                    f"{pool_id}: компонент потерял тип цели в метаданных."
                )
        if "system_types" in expectations:
            actual_system_types = set(
                primary_metadata.get("target", {}).get("systemTypes", [])
            )
            if actual_system_types != expectations["system_types"]:
                errors.append(
                    f"{pool_id}: потеряно ограничение подтипов экипировки."
                )
        attunement_weight = sum(
            int(metadata.get("attunement", {}).get("weight", 0))
            for metadata in all_metadata
            if isinstance(metadata, dict)
        )
        if attunement_weight < 4:
            errors.append(
                f"{pool_id}: составной профиль не достигает порога настройки."
            )

        if not any(
            component.get("activities")
            for component in components
            if isinstance(component, dict)
        ):
            errors.append(
                f"{pool_id}: составной профиль потерял активную площадную "
                "способность."
            )
        bundle_activities = [
            activity
            for component in components
            if isinstance(component, dict)
            for activity in component.get("activities", [])
            if isinstance(activity, dict)
        ]
        if len(bundle_activities) != 1:
            errors.append(
                f"{pool_id}: составной профиль должен содержать одну активную "
                "rider-activity."
            )
        else:
            bundle_activity = bundle_activities[0]
            if bundle_activity.get("uses") != {
                "spent": 0,
                "max": "3",
                "recovery": [
                    {"period": "lr", "type": "recoverAll"}
                ],
            }:
                errors.append(
                    f"{pool_id}: активная способность потеряла 3 заряда или "
                    "восстановление после продолжительного отдыха."
                )
            activity_consumption = (
                bundle_activity.get("consumption", {}).get("targets", [])
            )
            if not any(
                isinstance(target, dict)
                and target.get("type") == "activityUses"
                and str(target.get("value")) == "1"
                for target in activity_consumption
            ):
                errors.append(
                    f"{pool_id}: активная способность не расходует activityUses."
                )
        if not any(
            any(
                effect.get("transfer") is True
                for effect in component.get("effects", [])
                if isinstance(effect, dict)
            )
            for component in components
            if isinstance(component, dict)
        ):
            errors.append(
                f"{pool_id}: составной профиль потерял постоянный эффект "
                "владельца."
            )

    table = documents[enhancement_set_builder.TABLES_PACK][0]
    try:
        rolltable_builder.validate_ranges(validated["pools"][0]["results"])
    except rolltable_builder.RollTableBuilderError as error:
        errors.append(f"Тестовая RollTable: {error}")
    if table.get("formula") != "1d100" or len(table.get("results", [])) != 3:
        errors.append("Тестовая RollTable потеряла формулу или результаты.")
    if any(
        not str(result.get("documentUuid") or "").startswith(
            "Compendium.foundry-json-builder-enhancements."
            "enhancement-catalog.Item."
        )
        for result in table.get("results", [])
        if isinstance(result, dict)
    ):
        errors.append("RollTable ссылается не на каталог усилений.")

    broken = json.loads(json.dumps(source))
    broken["pools"][0]["results"][0]["range"] = [1, 39]
    try:
        enhancement_set_builder.validate_set(broken)
    except enhancement_set_builder.EnhancementSetBuilderError:
        pass
    else:
        errors.append("Валидатор не обнаружил разрыв d100-таблицы.")

    invalid_mode = json.loads(json.dumps(source))
    invalid_mode["enhancements"][0]["changes"][1]["mode"] = "override"
    try:
        enhancement_set_builder.validate_set(invalid_mode)
    except enhancement_set_builder.EnhancementSetBuilderError:
        pass
    else:
        errors.append(
            "Валидатор принял mode=override для system.damage.parts."
        )

    unknown_field = json.loads(json.dumps(source))
    unknown_field["enhancements"][0]["legacy_code"] = "obsolete"
    try:
        enhancement_set_builder.validate_set(unknown_field)
    except enhancement_set_builder.EnhancementSetBuilderError:
        pass
    else:
        errors.append("Валидатор усилений принял неизвестное поле.")

    invalid_attunement = json.loads(json.dumps(source))
    invalid_attunement["enhancements"][0]["attunement"] = {
        "weight": 5,
        "required": False,
    }
    try:
        enhancement_set_builder.validate_set(invalid_attunement)
    except enhancement_set_builder.EnhancementSetBuilderError:
        pass
    else:
        errors.append("Валидатор принял вес настройки больше 4.")

    invalid_rank = json.loads(json.dumps(source))
    invalid_rank["enhancements"][0]["rank"] = "legendary"
    try:
        enhancement_set_builder.validate_set(invalid_rank)
    except enhancement_set_builder.EnhancementSetBuilderError:
        pass
    else:
        errors.append("Валидатор принял неизвестный ранг усиления.")

    invalid_group = json.loads(json.dumps(source))
    invalid_group["groups"][0]["id"] = "invented_group"
    invalid_group["enhancements"][2]["group"] = "invented_group"
    try:
        enhancement_set_builder.validate_set(invalid_group)
    except enhancement_set_builder.EnhancementSetBuilderError:
        pass
    else:
        errors.append("Валидатор принял группу вне канонического реестра.")

    invalid_ordinary_occupancy = json.loads(json.dumps(source))
    invalid_ordinary_occupancy["enhancements"][0]["occupies_groups"] = [
        "additional_damage",
        "numeric_bonus",
    ]
    try:
        enhancement_set_builder.validate_set(invalid_ordinary_occupancy)
    except enhancement_set_builder.EnhancementSetBuilderError:
        pass
    else:
        errors.append(
            "Валидатор разрешил обычному усилению занимать несколько групп."
        )

    invalid_multi_property = json.loads(json.dumps(source))
    invalid_multi_property["enhancements"][2]["riders"]["effects"] = (
        json.loads(
            json.dumps(
                source["enhancements"][5]["riders"]["effects"]
            )
        )
    )
    try:
        enhancement_set_builder.validate_set(invalid_multi_property)
    except enhancement_set_builder.EnhancementSetBuilderError:
        pass
    else:
        errors.append(
            "Валидатор принял несколько самостоятельных свойств обычного "
            "усиления."
        )

    signature = json.loads(json.dumps(source["enhancements"][0]))
    signature["id"] = "signature_contract_test"
    signature["group"] = "signature_property"
    signature["rank"] = "unique"
    signature["occupies_groups"] = ["signature_property"]
    signature["signature_benefits"] = [
        "Уникальная постоянная часть",
        "Связанная активируемая часть",
    ]
    signature["changes"] = [
        change
        for change in signature["changes"]
        if change.get("key") in enhancement_builder.SUPPORT_CHANGE_KEYS
    ]
    signature["attunement"] = {"weight": 4, "required": True}
    signature["riders"]["effects"] = json.loads(
        json.dumps(source["enhancements"][5]["riders"]["effects"])
    )
    try:
        normalized_signature = enhancement_builder.validate_enhancement(
            signature,
            schema_version=6,
        )
    except enhancement_builder.EnhancementBuilderError as error:
        errors.append(f"Валидатор отклонил корректное signature_property: {error}")
    else:
        if normalized_signature["occupies_groups"] != ["signature_property"]:
            errors.append("signature_property потеряло отдельный слот.")
        if len(normalized_signature["signature_benefits"]) != 2:
            errors.append("signature_property потеряло два уникальных эффекта.")

    invalid_signature_occupancy = json.loads(json.dumps(signature))
    invalid_signature_occupancy["occupies_groups"] = [
        "signature_property",
        "active_power",
    ]
    try:
        enhancement_builder.validate_enhancement(
            invalid_signature_occupancy,
            schema_version=6,
        )
    except enhancement_builder.EnhancementBuilderError:
        pass
    else:
        errors.append(
            "Валидатор разрешил signature_property блокировать обычную группу."
        )

    invalid_signature_benefits = json.loads(json.dumps(signature))
    invalid_signature_benefits["signature_benefits"] = [
        "Только один уникальный эффект"
    ]
    try:
        enhancement_builder.validate_enhancement(
            invalid_signature_benefits,
            schema_version=6,
        )
    except enhancement_builder.EnhancementBuilderError:
        pass
    else:
        errors.append(
            "Валидатор принял signature_property без двух уникальных эффектов."
        )

    legacy_attunement = json.loads(json.dumps(source))
    legacy_attunement["schema_version"] = 3
    legacy_attunement["bundles"] = []
    legacy_attunement["enhancements"] = legacy_attunement["enhancements"][:7]
    legacy_attunement["pools"] = legacy_attunement["pools"][:5]
    legacy_attunement["enhancements"][0]["attunement"] = {
        "weight": 1,
        "required": False,
    }
    try:
        enhancement_set_builder.validate_set(legacy_attunement)
    except enhancement_set_builder.EnhancementSetBuilderError:
        pass
    else:
        errors.append(
            "Валидатор принял attunement в schema_version 3."
        )

    unbounded_rider = json.loads(json.dumps(source))
    active_rider = next(
        enhancement
        for enhancement in unbounded_rider["enhancements"]
        if enhancement["id"] == "active_self_speed_t1"
    )
    active_rider["riders"]["activities"][0].pop("unlimited", None)
    try:
        enhancement_set_builder.validate_set(unbounded_rider)
    except enhancement_set_builder.EnhancementSetBuilderError:
        pass
    else:
        errors.append(
            "Валидатор принял rider-activity без uses и unlimited: true."
        )

    unsupported_rider = json.loads(json.dumps(source))
    unsupported_rider["schema_version"] = 1
    unsupported_rider["bundles"] = []
    unsupported_rider["enhancements"] = unsupported_rider["enhancements"][:7]
    unsupported_rider["pools"] = unsupported_rider["pools"][:5]
    for enhancement in unsupported_rider["enhancements"]:
        enhancement["riders"] = {
            "activities": [],
            "effects": [],
            "items": [],
        }
    unsupported_rider["enhancements"][0]["riders"]["activities"] = [
        json.loads(json.dumps(source["enhancements"][3]["riders"]["activities"][0]))
    ]
    try:
        enhancement_set_builder.validate_set(unsupported_rider)
    except enhancement_set_builder.EnhancementSetBuilderError:
        pass
    else:
        errors.append(
            "Валидатор принял rider, который schema_version 1 не компилирует."
        )

    broken_rider_link = json.loads(json.dumps(source))
    broken_rider_link["enhancements"][3]["riders"]["effects"][0]["activity"] = 99
    try:
        enhancement_set_builder.build_set_documents(broken_rider_link)
    except (
        enhancement_set_builder.EnhancementSetBuilderError,
        enhancement_builder.EnhancementBuilderError,
    ):
        pass
    else:
        errors.append(
            "Компилятор принял rider-эффект со ссылкой на отсутствующую activity."
        )

    duplicate_bundle_group = json.loads(json.dumps(source))
    duplicate_bundle_group["bundles"][0]["enhancement_ids"][1] = (
        duplicate_bundle_group["bundles"][0]["enhancement_ids"][0]
    )
    try:
        enhancement_set_builder.validate_set(duplicate_bundle_group)
    except enhancement_set_builder.EnhancementSetBuilderError:
        pass
    else:
        errors.append(
            "Валидатор принял составное усиление с повторяющейся группой."
        )

    legacy_bundle = json.loads(json.dumps(source))
    legacy_bundle["schema_version"] = 2
    try:
        enhancement_set_builder.validate_set(legacy_bundle)
    except enhancement_set_builder.EnhancementSetBuilderError:
        pass
    else:
        errors.append(
            "Валидатор принял составное усиление в schema_version 2."
        )


def _audit_output_archive(errors: list[str]) -> None:
    archive_path = (
        ROOT
        / "output"
        / "enhancements"
        / "foundry-json-builder-enhancements.zip"
    )
    if not archive_path.is_file():
        return
    try:
        with ZipFile(archive_path) as archive:
            broken = archive.testzip()
            if broken is not None:
                errors.append(f"ZIP усилений повреждён: {broken}.")
            names = set(archive.namelist())
            manifest = json.loads(
                archive.read(
                    "foundry-json-builder-enhancements/module.json"
                )
            )
    except Exception as error:
        errors.append(f"Не удалось проверить ZIP усилений: {error}")
        return
    expected_packs = {
        "enhancers",
        "enhancement-catalog",
        "enhancement-tables",
    }
    actual_packs = {
        pack.get("name")
        for pack in manifest.get("packs", [])
        if isinstance(pack, dict)
    }
    if actual_packs != expected_packs:
        errors.append("module.json внутри ZIP содержит неверный список паков.")
    if str(manifest.get("version") or "") != project_config.ENHANCEMENTS_MODULE_VERSION:
        errors.append(
            "Версия модуля усилений внутри ZIP расходится с "
            "PROJECT_MANIFEST.json."
        )
    pack_folders = manifest.get("packFolders", [])
    expected_folder = {
        "name": build_enhancement_module.COMPENDIUM_FOLDER,
        "sorting": "m",
        "packs": [
            enhancement_set_builder.ENHANCERS_PACK,
            enhancement_set_builder.CATALOG_PACK,
            enhancement_set_builder.TABLES_PACK,
        ],
    }
    if pack_folders != [expected_folder]:
        errors.append(
            "Три пака усилений не собраны в общий раздел компендиума."
        )
    if not any(
        name.endswith("/scripts/enhancement-groups.mjs")
        for name in names
    ):
        errors.append("ZIP усилений не содержит контроллер групп.")
    for pack in expected_packs:
        prefix = f"foundry-json-builder-enhancements/packs/{pack}/"
        if not any(name.startswith(prefix) for name in names):
            errors.append(f"ZIP усилений не содержит LevelDB-пак {pack}.")

    report_path = archive_path.with_name(archive_path.stem + "_report.json")
    if report_path.is_file():
        try:
            report = _load_json(report_path)
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"Не удалось прочитать отчёт ZIP усилений: {error}")
        else:
            output = str(report.get("output") or "")
            if not output or ABSOLUTE_WORKSPACE_PATH.search(output):
                errors.append(
                    "Отчёт ZIP усилений содержит пустой или абсолютный "
                    "непереносимый путь output."
                )
            if report.get("schema_version") != enhancement_builder.SCHEMA_VERSION:
                errors.append("Отчёт ZIP содержит устаревшую schema_version.")
            if report.get("packs") != {
                enhancement_set_builder.ENHANCERS_PACK: 8,
                enhancement_set_builder.CATALOG_PACK: 17,
                enhancement_set_builder.TABLES_PACK: 8,
            }:
                errors.append("Отчёт ZIP содержит неверные количества документов.")


def audit() -> list[str]:
    errors: list[str] = []
    try:
        manifest = _load_json(MANIFEST_PATH)
    except (OSError, json.JSONDecodeError) as error:
        return [f"Не удалось прочитать PROJECT_MANIFEST.json: {error}"]

    manifest_files = _manifest_files(manifest)
    canonical_files = set(manifest_files)
    canonical_files.add("PROJECT_MANIFEST.json")
    if len(manifest_files) != len(set(manifest_files)):
        errors.append("Манифест содержит повторяющиеся канонические пути.")
    if manifest.get("package_entry_point") != "package_project.py":
        errors.append("Манифест не указывает канонический package_project.py.")
    manifest_targets = manifest.get("targets")
    if manifest_targets != project_config.TARGETS:
        errors.append("Целевые версии манифеста расходятся с project_config.")
    missing_docs = DOCUMENTATION_FILES - canonical_files
    if missing_docs:
        errors.append(
            "Манифест не зарегистрировал руководства: "
            + ", ".join(sorted(missing_docs))
        )
    try:
        template_registry = _load_json(ROOT / "templates.json")
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"Не удалось прочитать templates.json: {error}")
        template_registry = {}
    if template_registry.get("schema_version") != 1:
        errors.append("templates.json содержит неподдерживаемую schema_version.")
    template_sections = template_registry.get("templates")
    if not isinstance(template_sections, dict):
        errors.append("templates.json не содержит объект templates.")
    elif set(template_sections) != TEMPLATE_KEYS:
        errors.append(
            "Секции templates.json не совпадают с каноническим набором: "
            + ", ".join(sorted(set(template_sections) ^ TEMPLATE_KEYS))
        )
    if {spec.key for spec in builder_app.BUILDERS} != TEMPLATE_KEYS:
        errors.append(
            "Режимы builder_app не совпадают с секциями templates.json."
        )

    for legacy in sorted(LEGACY_RANDOM_FILES):
        if (ROOT / legacy).exists():
            errors.append(f"Остался устаревший random_upgrade-файл: {legacy}")
    for legacy in sorted(LEGACY_PROJECT_FILES):
        if (ROOT / legacy).exists():
            errors.append(f"Остался исключённый из проекта файл: {legacy}")
    for legacy in sorted(LEGACY_TEMPLATE_FILES):
        if (ROOT / legacy).exists():
            errors.append(f"Остался отдельный устаревший шаблон: {legacy}")

    for filename in _manifest_files(manifest):
        if not (ROOT / filename).is_file():
            errors.append(f"Отсутствует канонический файл: {filename}")

    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(ROOT)
        relative_text = relative.as_posix()
        if (
            "node_modules" in relative.parts
            or "_cacache" in relative.parts
            or path.name.endswith(".openai-download")
            or ".openai-download-" in path.name
        ):
            continue
        if NUMBERED_COPY.search(path.name):
            errors.append(f"Найдена нумерованная копия: {relative}")
        inspect_data_json = (
            path.suffix.casefold() == ".json"
            and (
                path.parent == ROOT
                or (relative.parts and relative.parts[0] == "output")
            )
        )
        if relative_text not in canonical_files and not inspect_data_json:
            continue
        if path.suffix.casefold() == ".json":
            try:
                document = _load_json(path)
            except (OSError, json.JSONDecodeError) as error:
                errors.append(f"Некорректный JSON {relative}: {error}")
            else:
                if _has_built_activities(document):
                    compatibility = midi_compat.audit_document(document)
                    errors.extend(
                        f"Midi-QOL/DAE {relative}: {issue}"
                        for issue in compatibility["errors"]
                    )
                _audit_target_versions(document, str(relative), errors)
                if path.parent == ROOT and isinstance(document, dict):
                    _audit_source_example(path, document, errors)
        elif path.suffix.casefold() == ".py":
            try:
                compile(
                    path.read_text(encoding="utf-8-sig"),
                    str(relative),
                    "exec",
                )
            except (OSError, SyntaxError, UnicodeError) as error:
                errors.append(f"Некорректный Python {relative}: {error}")
        elif path.suffix.casefold() == ".md":
            _audit_markdown_json(path, errors)

    errors.extend(
        f"Графическое приложение: {error}"
        for error in builder_app.self_test_errors()
    )
    _audit_enhancement_documents(errors)
    _audit_builder_contracts(errors)
    _audit_export_core_compatibility(errors)
    _audit_output_archive(errors)
    _audit_runtime_script(errors)

    launcher = ROOT / "start_builder_app.bat"
    try:
        launcher_text = launcher.read_text(encoding="utf-8-sig")
    except OSError as error:
        errors.append(f"Не удалось прочитать start_builder_app.bat: {error}")
    else:
        if "builder_app.py" not in launcher_text or "--self-test" not in launcher_text:
            errors.append(
                "start_builder_app.bat не выполняет предварительную "
                "самопроверку builder_app."
            )
    return errors


def main() -> int:
    errors = audit()
    if errors:
        print("Аудит завершён с ошибками:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Аудит завершён: ошибок не найдено.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
