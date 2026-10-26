#!/usr/bin/env python3
"""Сборка расходников Foundry VTT 13.351 / D&D5e 5.3.3."""

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

import equipment_builder as common
import enhancement_builder
import feat_builder
import midi_compat
import project_config


ROOT = Path(__file__).resolve().parent

TYPE_ALIASES = {
    "": "",
    "potion": "potion",
    "зелье": "potion",
    "poison": "poison",
    "яд": "poison",
    "food": "food",
    "еда": "food",
    "scroll": "scroll",
    "свиток": "scroll",
    "wand": "wand",
    "жезл": "wand",
    "rod": "rod",
    "скипетр": "rod",
    "trinket": "trinket",
    "безделушка": "trinket",
}

SUBTYPE_ALIASES = {
    "": "",
    "ingested": "ingested",
    "проглатываемый": "ingested",
    "contact": "contact",
    "контактный": "contact",
    "inhaled": "inhaled",
    "вдыхаемый": "inhaled",
    "injury": "injury",
    "ранение": "injury",
}


class ConsumableBuilderError(Exception):
    """Ошибка, из-за которой безопасная обработка невозможна."""


@dataclass
class Change:
    path: str
    action: str
    old: Any = None
    new: Any = None


@dataclass
class ConsumableResult:
    name: str
    status: str
    consumable_type: str
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
    consumables: list[ConsumableResult] = field(default_factory=list)

    def change(self, path: str, action: str, old: Any, new: Any) -> None:
        self.changes.append(Change(path, action, old, new))

    def warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


def _load_template() -> dict[str, Any]:
    try:
        value = common.load_template("consumable")
    except common.EquipmentBuilderError as error:
        raise ConsumableBuilderError(
            f"Не удалось прочитать шаблон расходника: {error}"
        ) from error
    return value


def _partial_item(source: dict[str, Any]) -> dict[str, Any]:
    item = deepcopy(_load_template())
    item["name"] = str(source.get("name") or "Безымянный расходник")
    if source.get("img") not in (None, ""):
        item["img"] = str(source["img"])
    if isinstance(source.get("system"), dict):
        common._deep_merge(item["system"], source["system"])

    for key in (
        "activities", "attuned", "attunement", "container", "damage",
        "description", "equipped", "identified", "identifier", "price",
        "properties", "quantity", "rarity", "source", "unidentified",
        "uses", "weight",
    ):
        if key in source and key != "activities":
            item["system"][key] = deepcopy(source[key])

    explicit_type = source.get("consumable_type")
    if explicit_type is not None:
        item["system"]["type"] = deepcopy(explicit_type)

    mechanics = source.get("mechanics")
    if isinstance(mechanics, dict):
        item["mechanics"] = deepcopy(mechanics)
    else:
        compact: dict[str, Any] = {}
        if isinstance(source.get("activities"), list):
            compact["activities"] = deepcopy(source["activities"])
        if isinstance(source.get("effects"), list):
            compact["effects"] = deepcopy(source["effects"])
        if compact:
            item["mechanics"] = compact
    if isinstance(source.get("flags"), dict):
        item["flags"] = deepcopy(source["flags"])
    item["type"] = "consumable"
    return item


def _canonical_type(value: Any, aliases: dict[str, str]) -> str:
    text = str(value or "").casefold().replace("ё", "е").strip()
    return aliases.get(text, str(value or "").strip())


def build_enchantment_consumable(
    pool: dict[str, Any],
    enhancements: list[dict[str, Any]],
    *,
    set_id: str,
    module_id: str,
    table_pack: str,
    table_id: str,
    document_id: str,
    schema_version: int = enhancement_builder.SCHEMA_VERSION,
    bundles: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Создаёт один расходный усилитель со штатной activity ``Enchant``."""
    target = pool.get("target")
    enhancer = pool.get("enhancer")
    if not isinstance(target, dict) or not isinstance(enhancer, dict):
        raise ConsumableBuilderError("Пул должен содержать target и enhancer.")
    item_types = target.get("item_types")
    if not isinstance(item_types, list) or len(item_types) != 1:
        raise ConsumableBuilderError(
            "Enchant-пул должен иметь ровно один target.item_type."
        )

    bundles = bundles or {}
    component_effects: dict[str, dict[str, Any]] = {}
    component_activities: dict[str, list[dict[str, Any]]] = {}
    component_rider_effects: dict[str, list[dict[str, Any]]] = {}
    for enhancement in enhancements:
        activities, active_effects = enhancement_builder.build_rider_documents(
            enhancement,
            set_id=set_id,
            schema_version=schema_version,
        )
        component_activities[enhancement["id"]] = activities
        component_rider_effects[enhancement["id"]] = active_effects
        component_effects[enhancement["id"]] = (
            enhancement_builder.build_enchantment_effect(
            enhancement,
            set_id=set_id,
            rider_ids={
                "activity": [
                    activity["_id"] for activity in activities
                ],
                "effect": [
                    effect["_id"] for effect in active_effects
                ],
                "item": [],
            },
            schema_version=schema_version,
        )
        )
        if schema_version >= 5:
            metadata = component_effects[enhancement["id"]]["flags"][
                enhancement_builder.MODULE_ID
            ]["enhancement"]
            metadata["target"] = {
                "itemTypes": deepcopy(item_types),
                "systemTypes": deepcopy(target.get("system_types") or []),
                "categories": deepcopy(target.get("categories") or []),
                "properties": deepcopy(target.get("properties") or []),
                "allowMagical": bool(target.get("allow_magical", True)),
            }

    profile_effects: list[dict[str, Any]] = []
    rider_activities: list[dict[str, Any]] = []
    rider_effects: list[dict[str, Any]] = []
    profile_data: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for result in pool["results"]:
        if "enhancement_id" in result:
            enhancement_id = result["enhancement_id"]
            profile = component_effects[enhancement_id]
            profile_effects.append(profile)
            rider_activities.extend(component_activities[enhancement_id])
            rider_effects.extend(component_rider_effects[enhancement_id])
            profile_data.append(
                (
                    result,
                    {
                        "name": profile["name"],
                        "description": profile["description"],
                        "effect": profile,
                    },
                )
            )
            continue

        bundle = bundles[result["bundle_id"]]
        component_ids = list(bundle["enhancement_ids"])
        primary_id = component_ids[0]
        primary = deepcopy(component_effects[primary_id])
        primary_metadata = primary["flags"][enhancement_builder.MODULE_ID][
            "enhancement"
        ]
        primary_metadata["bundle"] = {
            "id": bundle["id"],
            "name": bundle["name"],
            "primaryName": component_effects[primary_id]["name"],
            "components": [
                {
                    "effect": deepcopy(component_effects[component_id]),
                    "activities": deepcopy(component_activities[component_id]),
                    "effects": deepcopy(
                        component_rider_effects[component_id]
                    ),
                }
                for component_id in component_ids[1:]
            ],
        }
        primary["name"] = bundle["name"]
        primary["img"] = bundle["img"]
        primary["description"] = (
            f"<p>{html.escape(bundle['description'])}</p>"
            f"<p><strong>Состав:</strong> "
            + ", ".join(
                html.escape(component_effects[component_id]["name"])
                for component_id in component_ids
            )
            + ".</p>"
        )
        profile_effects.append(primary)
        rider_activities.extend(component_activities[primary_id])
        rider_effects.extend(component_rider_effects[primary_id])
        profile_data.append(
            (
                result,
                {
                    "name": bundle["name"],
                    "description": bundle["description"],
                    "effect": primary,
                },
            )
        )
    activity_id = enhancement_builder.stable_id(
        f"{set_id}:activity", str(pool["id"])
    )
    profile_refs = []
    for _result, profile_data_entry in profile_data:
        effect = profile_data_entry["effect"]
        riders = effect["flags"]["dnd5e"]["enchantment"]["riders"]
        profile_refs.append(
            {
                "_id": effect["_id"],
                "level": {"min": None, "max": None},
                "riders": deepcopy(riders),
            }
        )

    table_uuid = (
        f"Compendium.{module_id}.{table_pack}.RollTable.{table_id}"
    )
    description = str(enhancer.get("description") or "").strip()
    instructions = (
        f"<p><strong>Порядок применения:</strong> сначала бросьте "
        f"@UUID[{table_uuid}]{{{html.escape(str(pool['name']))}}}, затем "
        "используйте усилитель, выберите профиль с выпавшим названием и "
        "перетащите предмет в область зачарования.</p>"
        "<p>Бросок таблицы не расходует усилитель. Одно использование "
        "расходуется только после успешного наложения.</p>"
    )
    profiles = "".join(
        f"<li>{result['range'][0]}–{result['range'][1]}: "
        f"<strong>{html.escape(profile['name'])}</strong> — "
        f"{html.escape(profile['description'])}</li>"
        for result, profile in profile_data
    )

    uses = enhancer.get("uses")
    if not isinstance(uses, dict):
        raise ConsumableBuilderError("enhancer.uses должен быть объектом.")
    item = deepcopy(_load_template())
    item.update(
        {
            "_id": document_id,
            "name": str(enhancer.get("name") or "Усилитель"),
            "type": "consumable",
            "img": str(
                enhancer.get("img")
                or "icons/commodities/treasure/token-runed-os-grey.webp"
            ),
            "effects": profile_effects + rider_effects,
            "flags": {
                "dnd5e": {
                    "riders": {"activity": [], "effect": [], "item": []}
                },
                enhancement_builder.MODULE_ID: {
                    "enhancer": {
                        "setId": set_id,
                        "poolId": str(pool["id"]),
                        "tier": int(pool["tier"]),
                        "tableUuid": table_uuid,
                    }
                },
            },
        }
    )
    system = item["system"]
    system["identifier"] = str(pool["id"]).replace("_", "-")
    system["description"] = {
        "value": (
            f"<p>{html.escape(description)}</p>{instructions}"
            f"<h3>Возможные усиления</h3><ol>{profiles}</ol>"
        ),
        "chat": "",
    }
    system["rarity"] = str(enhancer.get("rarity") or "")
    system["type"] = {
        "value": str(enhancer.get("consumable_type") or "trinket"),
        "subtype": "",
    }
    system["uses"] = {
        "max": str(uses.get("max") or "1"),
        "spent": int(uses.get("spent") or 0),
        "recovery": [],
        "autoDestroy": bool(uses.get("autoDestroy", True)),
    }
    enchant_activity = {
            "_id": activity_id,
            "type": "enchant",
            "name": f"Применить: {pool['name']}",
            "img": "",
            "sort": 0,
            "activation": {
                "type": "action",
                "value": 1,
                "override": False,
                "condition": "",
            },
            "consumption": {
                "scaling": {"allowed": False, "max": ""},
                "spellSlot": True,
                "targets": [
                    {"type": "itemUses", "value": "1", "target": ""}
                ],
            },
            "description": {
                "chatFlavor": (
                    "Выберите профиль с выпавшим названием и перетащите "
                    "подходящий предмет в область зачарования."
                )
            },
            "duration": {
                "units": "inst",
                "concentration": False,
                "override": False,
            },
            "effects": profile_refs,
            "range": {"override": False, "units": "touch", "special": ""},
            "target": {
                "template": {
                    "contiguous": False,
                    "units": "ft",
                    "type": "",
                },
                "affects": {
                    "choice": False,
                    "count": "1",
                    "type": "object",
                },
                "override": False,
                "prompt": True,
            },
            "uses": {"spent": 0, "recovery": [], "max": ""},
            "enchant": {"identifier": ""},
            "restrictions": {
                "allowMagical": bool(target.get("allow_magical", True)),
                "categories": deepcopy(target.get("categories") or []),
                "properties": deepcopy(target.get("properties") or []),
                "type": str(item_types[0]),
            },
            "appliedEffects": [
                effect["_id"] for effect in profile_effects
            ],
            "visibility": {
                "requireMagic": True,
                "level": {"min": None, "max": None},
                "identifier": "",
            },
    }
    midi_compat.normalize_activity(enchant_activity)
    system["activities"] = {
        activity_id: enchant_activity,
        **{
            activity["_id"]: activity
            for activity in rider_activities
        },
    }
    return item


def _normalize_item(item: dict[str, Any], report: BuildReport, path: str) -> None:
    name = str(item.get("name") or "").strip() or "Безымянный расходник"
    item["name"] = name
    item["type"] = "consumable"
    common._default(
        item, "img", "systems/dnd5e/icons/svg/items/consumable.svg", report, path
    )
    common._default(item, "folder", None, report, path)
    common._default(item, "flags", {}, report, path)
    common._default(
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
    system = common._ensure_dict(item, "system", report, path)
    effects = common._ensure_list(item, "effects", report, path)

    description = system.get("description")
    if isinstance(description, str):
        system["description"] = {"value": description, "chat": ""}
    description = common._ensure_dict(
        system, "description", report, f"{path}.system"
    )
    common._default(description, "value", "", report, f"{path}.system.description")
    common._default(description, "chat", "", report, f"{path}.system.description")
    common._default(system, "identifier", common._slug(name), report, f"{path}.system")
    common._default(system, "identified", True, report, f"{path}.system")
    common._default(system, "quantity", 1, report, f"{path}.system")
    common._default(system, "container", None, report, f"{path}.system")
    common._default(system, "rarity", "", report, f"{path}.system")
    common._default(system, "attunement", "", report, f"{path}.system")
    common._default(system, "attuned", False, report, f"{path}.system")
    common._default(system, "equipped", False, report, f"{path}.system")
    common._default(system, "properties", [], report, f"{path}.system")

    source = common._ensure_dict(system, "source", report, f"{path}.system")
    common._default(source, "revision", 1, report, f"{path}.system.source")
    common._default(source, "rules", "2024", report, f"{path}.system.source")
    for key, defaults in (
        ("unidentified", {"description": ""}),
        ("weight", {"value": 0, "units": "lb"}),
        ("price", {"value": 0, "denomination": "gp"}),
    ):
        target = common._ensure_dict(system, key, report, f"{path}.system")
        for child, default in defaults.items():
            common._default(target, child, default, report, f"{path}.system.{key}")

    type_data = system.get("type")
    if isinstance(type_data, str):
        type_data = {"value": type_data, "subtype": ""}
        system["type"] = type_data
    type_data = common._ensure_dict(system, "type", report, f"{path}.system")
    type_data["value"] = _canonical_type(type_data.get("value"), TYPE_ALIASES)
    type_data["subtype"] = _canonical_type(
        type_data.get("subtype"), SUBTYPE_ALIASES
    )

    uses = common._ensure_dict(system, "uses", report, f"{path}.system")
    common._default(uses, "max", "1", report, f"{path}.system.uses")
    common._default(uses, "spent", 0, report, f"{path}.system.uses")
    common._default(uses, "autoDestroy", True, report, f"{path}.system.uses")
    common._ensure_list(uses, "recovery", report, f"{path}.system.uses")

    activities = system.get("activities")
    if isinstance(activities, list):
        activities = {
            str(a.get("_id") or common._activity_id(i)): a
            for i, a in enumerate(activities)
            if isinstance(a, dict)
        }
        for key, activity in activities.items():
            activity["_id"] = key
        system["activities"] = activities
    elif not isinstance(activities, dict):
        activities = {}
        system["activities"] = activities

    before = len(activities)
    if before:
        common._audit_existing_activities(
            activities, name, report, f"{path}.system.activities"
        )
        report.consumables.append(
            ConsumableResult(
                name, "preserved", type_data["value"], before, before,
                len(effects),
                "Существующие activities сохранены.",
            )
        )
        return

    mechanics = common._extract_mechanics(item)
    if not isinstance(mechanics.get("uses"), dict):
        mechanics["uses"] = deepcopy(uses)
    common._apply_uses(system, mechanics, report, f"{path}.system")
    mechanics_uses = mechanics.get("uses")
    if isinstance(mechanics_uses, dict) and "autoDestroy" in mechanics_uses:
        uses["autoDestroy"] = bool(mechanics_uses["autoDestroy"])
    common._consume_mechanics(item, system, report, path)
    built_activities = common._build_activities(mechanics, name, report)
    built_effects = feat_builder._build_effects(
        mechanics, built_activities, name, report, effects
    )
    for effect in built_effects:
        effects.append(effect)
    for activity in built_activities:
        activities[activity["_id"]] = activity

    status = (
        "created_activities" if built_activities
        else "created_effects" if built_effects
        else "passive_or_manual"
    )
    report.consumables.append(
        ConsumableResult(
            name, status, type_data["value"], before, len(activities),
            len(effects),
            f"Activities: {len(built_activities)}; Active Effects: {len(built_effects)}."
        )
    )


def normalize_document(
    source: dict[str, Any], source_name: str = ""
) -> tuple[dict[str, Any], BuildReport, str]:
    if not isinstance(source, dict):
        raise ConsumableBuilderError("Корень JSON должен быть объектом.")
    report = BuildReport(source=source_name)
    document_type = source.get("type")
    is_actor = document_type == "npc" or (
        isinstance(source.get("items"), list)
        and isinstance(source.get("system"), dict)
        and document_type != "consumable"
    )
    if is_actor:
        document = deepcopy(source)
        items = document.get("items")
        if not isinstance(items, list):
            raise ConsumableBuilderError("У актёра items должен быть массивом.")
        for index, item in enumerate(items):
            if isinstance(item, dict) and item.get("type") == "consumable":
                if not isinstance(item.get("system"), dict):
                    item = _partial_item(item)
                    items[index] = item
                _normalize_item(item, report, f"$.items[{index}]")
        return document, report, "actor"
    document = (
        deepcopy(source)
        if document_type == "consumable" and isinstance(source.get("system"), dict)
        else _partial_item(source)
    )
    _normalize_item(document, report, "$")
    return document, report, "consumable"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            value = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise ConsumableBuilderError(f"Не удалось прочитать {path}: {error}") from error
    if not isinstance(value, dict):
        raise ConsumableBuilderError("Корень JSON должен быть объектом.")
    return value


def _atomic_json_write(path: Path, data: Any, indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_name = temporary.name
            json.dump(data, temporary, ensure_ascii=False, indent=indent)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except OSError as error:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise ConsumableBuilderError(f"Не удалось записать {path}: {error}") from error


def _safe_filename(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .") or "Расходник"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Собирает расходники Foundry VTT.")
    parser.add_argument("source", nargs="?", type=Path, default=Path("input/consumable.json"))
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--report", type=Path, default=Path("logs/consumable_builder_report.json"))
    parser.add_argument("--indent", type=int, default=2, choices=range(1, 9))
    args = parser.parse_args(argv)
    try:
        source = _load_json(args.source)
        document, report, kind = normalize_document(source, str(args.source))
        folder = "actors" if kind == "actor" else "consumables"
        output = args.output or Path("output") / folder / (
            f"{_safe_filename(str(document.get('name') or 'Расходник'))}_foundry.json"
        )
        report.output = str(output)
        _atomic_json_write(output, document, args.indent)
        _atomic_json_write(args.report, asdict(report), args.indent)
    except ConsumableBuilderError as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return 1
    print(f"Готово: {output}")
    print(f"Расходников: {len(report.consumables)}; предупреждений: {len(report.warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
