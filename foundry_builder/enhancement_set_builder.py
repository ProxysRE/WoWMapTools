#!/usr/bin/env python3
"""Проверка enhancement_set и создание исходников компедиумов."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

import consumable_builder
import enhancement_builder
import rolltable_builder


MODULE_ID = enhancement_builder.MODULE_ID
ENHANCERS_PACK = "enhancers"
CATALOG_PACK = "enhancement-catalog"
TABLES_PACK = "enhancement-tables"
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
ROOT_FIELDS = {
    "schema_version",
    "type",
    "set",
    "groups",
    "enhancements",
    "bundles",
    "pools",
}
SET_FIELDS = {"id", "name", "version", "description"}
GROUP_FIELDS = {"id", "name", "rule", "description"}
BUNDLE_FIELDS = {
    "id",
    "name",
    "img",
    "tier",
    "description",
    "enhancement_ids",
}
POOL_FIELDS = {"id", "name", "tier", "roll", "target", "enhancer", "results"}
ROLL_FIELDS = {"formula", "domain"}
TARGET_FIELDS = {
    "item_types",
    "system_types",
    "categories",
    "properties",
    "allow_magical",
}
ENHANCER_FIELDS = {
    "name",
    "img",
    "description",
    "rarity",
    "consumable_type",
    "uses",
}
USES_FIELDS = {"max", "spent", "autoDestroy"}
RESULT_FIELDS = {"range", "enhancement_id", "bundle_id"}


class EnhancementSetBuilderError(Exception):
    """Набор усилений нельзя безопасно собрать."""


def _require_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EnhancementSetBuilderError(f"{path} должен быть объектом.")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise EnhancementSetBuilderError(f"{path} должен быть непустым массивом.")
    return value


def _reject_unknown_fields(
    source: dict[str, Any],
    allowed: set[str],
    path: str,
) -> None:
    unknown = sorted(set(source) - allowed)
    if unknown:
        raise EnhancementSetBuilderError(
            f"{path} содержит неподдерживаемые поля: {', '.join(unknown)}."
        )


def _validate_pool_target(
    pool: dict[str, Any],
    enhancements: list[dict[str, Any]],
    path: str,
    *,
    schema_version: int,
) -> None:
    target = _require_object(pool.get("target"), f"{path}.target")
    _reject_unknown_fields(target, TARGET_FIELDS, f"{path}.target")
    item_types = target.get("item_types")
    if not isinstance(item_types, list) or len(item_types) != 1:
        raise EnhancementSetBuilderError(
            f"{path}.target.item_types должен содержать ровно один тип."
        )
    item_type = str(item_types[0])
    if item_type not in {"weapon", "equipment", "consumable", "tool", "loot"}:
        raise EnhancementSetBuilderError(
            f"{path}.target.item_types содержит неподдерживаемый тип {item_type}."
        )
    for key in ("system_types", "categories", "properties"):
        if not isinstance(target.get(key), list):
            raise EnhancementSetBuilderError(
                f"{path}.target.{key} должен быть массивом."
            )
        values = target[key]
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise EnhancementSetBuilderError(
                f"{path}.target.{key} должен содержать непустые строки."
            )
        if len(values) != len(set(values)):
            raise EnhancementSetBuilderError(
                f"{path}.target.{key} содержит повторяющиеся значения."
            )
    if target["system_types"] and schema_version < 5:
        raise EnhancementSetBuilderError(
            f"{path}.target.system_types поддерживается только начиная "
            "со schema_version 5."
        )
    if not isinstance(target.get("allow_magical"), bool):
        raise EnhancementSetBuilderError(
            f"{path}.target.allow_magical должен быть true или false."
        )

    for enhancement in enhancements:
        keys = {change["key"] for change in enhancement["changes"]}
        weapon_only = any(
            key.startswith("system.damage")
            or key == "system.magicalBonus"
            or key.startswith("activities[attack]")
            for key in keys
        )
        equipment_only = "system.armor.magicalBonus" in keys
        if weapon_only and item_type != "weapon":
            raise EnhancementSetBuilderError(
                f"{path}: усиление {enhancement['id']} предназначено для оружия."
            )
        if equipment_only and item_type != "equipment":
            raise EnhancementSetBuilderError(
                f"{path}: усиление {enhancement['id']} предназначено для экипировки."
            )
        if (
            equipment_only
            and target["system_types"]
            and not set(target["system_types"]).intersection(
                {"light", "medium", "heavy", "natural", "shield"}
            )
        ):
            raise EnhancementSetBuilderError(
                f"{path}: броневой бонус требует подтип light, medium, heavy, "
                "natural или shield."
            )


def validate_set(source: Any) -> dict[str, Any]:
    """Проверяет полный контракт enhancement_set."""
    if not isinstance(source, dict):
        raise EnhancementSetBuilderError("Корень JSON должен быть объектом.")
    try:
        schema_version = enhancement_builder._require_schema_version(
            source.get("schema_version")
        )
    except enhancement_builder.EnhancementBuilderError as error:
        raise EnhancementSetBuilderError(str(error)) from error
    if source.get("type") != "enhancement_set":
        raise EnhancementSetBuilderError('type должен быть "enhancement_set".')

    result = deepcopy(source)
    result["schema_version"] = schema_version
    _reject_unknown_fields(result, ROOT_FIELDS, "$")
    set_data = _require_object(result.get("set"), "$.set")
    _reject_unknown_fields(set_data, SET_FIELDS, "$.set")
    set_id = enhancement_builder._require_id(set_data.get("id"), "$.set.id")
    set_data["id"] = set_id
    set_data["name"] = enhancement_builder._require_text(
        set_data.get("name"), "$.set.name"
    )
    set_data["version"] = enhancement_builder._require_text(
        set_data.get("version"), "$.set.version"
    )
    if not SEMVER.fullmatch(set_data["version"]):
        raise EnhancementSetBuilderError(
            "$.set.version должен быть семантической версией вида 1.2.3."
        )
    set_data["description"] = enhancement_builder._require_text(
        set_data.get("description"), "$.set.description"
    )

    groups: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(_require_list(result.get("groups"), "$.groups")):
        path = f"$.groups[{index}]"
        group = _require_object(raw, path)
        _reject_unknown_fields(group, GROUP_FIELDS, path)
        group_id = enhancement_builder._require_id(group.get("id"), f"{path}.id")
        if group_id in groups:
            raise EnhancementSetBuilderError(f"{path}.id повторяется: {group_id}.")
        if group.get("rule") != "replace_any":
            raise EnhancementSetBuilderError(
                f'{path}.rule в текущей версии должен быть "replace_any".'
            )
        if (
            schema_version >= 5
            and group_id not in enhancement_builder.CANONICAL_GROUPS
        ):
            raise EnhancementSetBuilderError(
                f"{path}.id отсутствует в окончательном реестре групп."
            )
        group["id"] = group_id
        group["name"] = enhancement_builder._require_text(
            group.get("name"), f"{path}.name"
        )
        group["description"] = enhancement_builder._require_text(
            group.get("description"), f"{path}.description"
        )
        groups[group_id] = group

    enhancements: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(
        _require_list(result.get("enhancements"), "$.enhancements")
    ):
        try:
            enhancement = enhancement_builder.validate_enhancement(
                raw,
                f"$.enhancements[{index}]",
                schema_version=schema_version,
            )
        except enhancement_builder.EnhancementBuilderError as error:
            raise EnhancementSetBuilderError(str(error)) from error
        enhancement_id = enhancement["id"]
        if enhancement_id in enhancements:
            raise EnhancementSetBuilderError(
                f"$.enhancements[{index}].id повторяется: {enhancement_id}."
            )
        if enhancement["group"] not in groups:
            raise EnhancementSetBuilderError(
                f"$.enhancements[{index}].group ссылается на неизвестную группу."
            )
        enhancements[enhancement_id] = enhancement

    raw_bundles = result.get("bundles", [])
    if not isinstance(raw_bundles, list):
        raise EnhancementSetBuilderError("$.bundles должен быть массивом.")
    if raw_bundles and schema_version < 3:
        raise EnhancementSetBuilderError(
            "$.bundles поддерживается только начиная со schema_version 3."
        )
    bundles: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_bundles):
        path = f"$.bundles[{index}]"
        bundle = _require_object(raw, path)
        _reject_unknown_fields(bundle, BUNDLE_FIELDS, path)
        bundle_id = enhancement_builder._require_id(
            bundle.get("id"), f"{path}.id"
        )
        if bundle_id in bundles or bundle_id in enhancements:
            raise EnhancementSetBuilderError(
                f"{path}.id повторяется среди усилений и связок: {bundle_id}."
            )
        bundle["id"] = bundle_id
        bundle["name"] = enhancement_builder._require_text(
            bundle.get("name"), f"{path}.name"
        )
        bundle["description"] = enhancement_builder._require_text(
            bundle.get("description"), f"{path}.description"
        )
        bundle["img"] = str(
            bundle.get("img")
            or "icons/magic/symbols/runes-star-pentagon-orange.webp"
        )
        tier = bundle.get("tier")
        if isinstance(tier, bool) or not isinstance(tier, int) or tier < 1:
            raise EnhancementSetBuilderError(
                f"{path}.tier должен быть целым числом от 1."
            )
        enhancement_ids = bundle.get("enhancement_ids")
        if (
            not isinstance(enhancement_ids, list)
            or not 2 <= len(enhancement_ids) <= 4
        ):
            raise EnhancementSetBuilderError(
                f"{path}.enhancement_ids должен содержать от 2 до 4 усилений."
            )
        normalized_ids: list[str] = []
        occupied_groups: set[str] = set()
        for component_index, raw_id in enumerate(enhancement_ids):
            component_id = enhancement_builder._require_id(
                raw_id,
                f"{path}.enhancement_ids[{component_index}]",
            )
            if component_id not in enhancements:
                raise EnhancementSetBuilderError(
                    f"{path}.enhancement_ids[{component_index}] ссылается "
                    f"на неизвестное усиление {component_id}."
                )
            component = enhancements[component_id]
            if component["tier"] != tier:
                raise EnhancementSetBuilderError(
                    f"{path}: тир компонента {component_id} не совпадает "
                    "с тиром составного усиления."
                )
            component_occupied = set(
                component.get("occupies_groups") or [component["group"]]
            )
            overlap = occupied_groups.intersection(component_occupied)
            if overlap:
                raise EnhancementSetBuilderError(
                    f"{path}: компоненты занимают пересекающиеся группы: "
                    + ", ".join(sorted(overlap))
                    + "."
                )
            normalized_ids.append(component_id)
            occupied_groups.update(component_occupied)
        if len(normalized_ids) != len(set(normalized_ids)):
            raise EnhancementSetBuilderError(
                f"{path}.enhancement_ids содержит повторяющиеся усиления."
            )
        bundle["tier"] = tier
        bundle["enhancement_ids"] = normalized_ids
        bundles[bundle_id] = bundle

    pools: list[dict[str, Any]] = []
    pool_ids: set[str] = set()
    used_enhancements: set[str] = set()
    used_bundles: set[str] = set()
    for index, raw in enumerate(_require_list(result.get("pools"), "$.pools")):
        path = f"$.pools[{index}]"
        pool = _require_object(raw, path)
        _reject_unknown_fields(pool, POOL_FIELDS, path)
        pool_id = enhancement_builder._require_id(pool.get("id"), f"{path}.id")
        if pool_id in pool_ids:
            raise EnhancementSetBuilderError(f"{path}.id повторяется: {pool_id}.")
        pool_ids.add(pool_id)
        pool["id"] = pool_id
        pool["name"] = enhancement_builder._require_text(
            pool.get("name"), f"{path}.name"
        )
        tier = pool.get("tier")
        if isinstance(tier, bool) or not isinstance(tier, int) or tier < 1:
            raise EnhancementSetBuilderError(
                f"{path}.tier должен быть целым числом от 1."
            )
        try:
            results = rolltable_builder.validate_ranges(
                pool.get("results"), path=f"{path}.results"
            )
        except rolltable_builder.RollTableBuilderError as error:
            raise EnhancementSetBuilderError(str(error)) from error
        selected: list[dict[str, Any]] = []
        selected_profile_names: list[str] = []
        selected_component_ids: set[str] = set()
        for result_index, table_result in enumerate(results):
            if "enhancement_id" in table_result:
                enhancement_id = table_result["enhancement_id"]
                if enhancement_id not in enhancements:
                    raise EnhancementSetBuilderError(
                        f"{path}.results[{result_index}] ссылается на неизвестное "
                        f"усиление {enhancement_id}."
                    )
                enhancement = enhancements[enhancement_id]
                if enhancement["tier"] != tier:
                    raise EnhancementSetBuilderError(
                        f"{path}.results[{result_index}]: тир усиления "
                        "не совпадает с тиром пула."
                    )
                component_ids = [enhancement_id]
                selected_profile_names.append(enhancement["name"].casefold())
                used_enhancements.add(enhancement_id)
            else:
                if schema_version < 3:
                    raise EnhancementSetBuilderError(
                        f"{path}.results[{result_index}].bundle_id поддерживается "
                        "только начиная со schema_version 3."
                    )
                bundle_id = table_result["bundle_id"]
                if bundle_id not in bundles:
                    raise EnhancementSetBuilderError(
                        f"{path}.results[{result_index}] ссылается на неизвестное "
                        f"составное усиление {bundle_id}."
                    )
                bundle = bundles[bundle_id]
                if bundle["tier"] != tier:
                    raise EnhancementSetBuilderError(
                        f"{path}.results[{result_index}]: тир составного "
                        "усиления не совпадает с тиром пула."
                    )
                component_ids = list(bundle["enhancement_ids"])
                selected_profile_names.append(bundle["name"].casefold())
                used_bundles.add(bundle_id)
                used_enhancements.update(component_ids)
            overlap = selected_component_ids.intersection(component_ids)
            if overlap:
                raise EnhancementSetBuilderError(
                    f"{path}.results[{result_index}] повторно использует "
                    "компоненты другого профиля: "
                    + ", ".join(sorted(overlap))
                    + "."
                )
            selected_component_ids.update(component_ids)
            selected.extend(enhancements[item] for item in component_ids)
        pool["results"] = results
        if len(selected_profile_names) != len(set(selected_profile_names)):
            raise EnhancementSetBuilderError(
                f"{path}.results содержит профили с одинаковыми названиями."
            )
        _validate_pool_target(
            pool,
            selected,
            path,
            schema_version=schema_version,
        )

        roll = _require_object(pool.get("roll"), f"{path}.roll")
        _reject_unknown_fields(roll, ROLL_FIELDS, f"{path}.roll")
        if roll.get("formula") != "1d100" or roll.get("domain") != [1, 100]:
            raise EnhancementSetBuilderError(
                f"{path}.roll должен содержать 1d100 и domain [1, 100]."
            )
        enhancer = _require_object(pool.get("enhancer"), f"{path}.enhancer")
        _reject_unknown_fields(enhancer, ENHANCER_FIELDS, f"{path}.enhancer")
        for key in ("name", "description"):
            enhancer[key] = enhancement_builder._require_text(
                enhancer.get(key), f"{path}.enhancer.{key}"
            )
        if enhancer.get("consumable_type") != "trinket":
            raise EnhancementSetBuilderError(
                f'{path}.enhancer.consumable_type должен быть "trinket".'
            )
        uses = _require_object(enhancer.get("uses"), f"{path}.enhancer.uses")
        _reject_unknown_fields(uses, USES_FIELDS, f"{path}.enhancer.uses")
        if (
            str(uses.get("max")) != "1"
            or uses.get("spent") != 0
            or uses.get("autoDestroy") is not True
        ):
            raise EnhancementSetBuilderError(
                f"{path}.enhancer.uses должен описывать одноразовый расходник."
            )
        pools.append(pool)

    unused = sorted(set(enhancements) - used_enhancements)
    if unused:
        raise EnhancementSetBuilderError(
            "$.enhancements содержит записи, не используемые ни одним пулом: "
            + ", ".join(unused)
            + "."
        )
    unused_bundles = sorted(set(bundles) - used_bundles)
    if unused_bundles:
        raise EnhancementSetBuilderError(
            "$.bundles содержит записи, не используемые ни одним пулом: "
            + ", ".join(unused_bundles)
            + "."
        )

    result["set"] = set_data
    result["groups"] = list(groups.values())
    result["enhancements"] = list(enhancements.values())
    result["bundles"] = list(bundles.values())
    result["pools"] = pools
    return result


def build_set_documents(source: Any) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Создаёт читаемые документы для трёх компедиумов."""
    validated = validate_set(source)
    set_data = validated["set"]
    set_id = set_data["id"]
    schema_version = validated["schema_version"]
    enhancements = {
        enhancement["id"]: enhancement
        for enhancement in validated["enhancements"]
    }
    bundles = {
        bundle["id"]: bundle
        for bundle in validated["bundles"]
    }
    catalog_ids = {
        enhancement_id: enhancement_builder.stable_id(
            f"{set_id}:catalog", enhancement_id
        )
        for enhancement_id in enhancements
    }
    bundle_catalog_ids = {
        bundle_id: enhancement_builder.stable_id(
            f"{set_id}:bundle-catalog", bundle_id
        )
        for bundle_id in bundles
    }
    catalog = [
        enhancement_builder.build_catalog_item(
            enhancement,
            set_id=set_id,
            document_id=catalog_ids[enhancement["id"]],
            schema_version=schema_version,
        )
        for enhancement in enhancements.values()
    ]
    catalog.extend(
        enhancement_builder.build_bundle_catalog_item(
            bundle,
            [
                enhancements[enhancement_id]
                for enhancement_id in bundle["enhancement_ids"]
            ],
            set_id=set_id,
            document_id=bundle_catalog_ids[bundle["id"]],
        )
        for bundle in bundles.values()
    )
    combined_catalog_ids = {
        **catalog_ids,
        **{
            f"bundle:{bundle_id}": document_id
            for bundle_id, document_id in bundle_catalog_ids.items()
        },
    }

    tables: list[dict[str, Any]] = []
    enhancers: list[dict[str, Any]] = []
    for pool in validated["pools"]:
        selected = [
            enhancements[enhancement_id]
            for result in pool["results"]
            for enhancement_id in (
                [result["enhancement_id"]]
                if "enhancement_id" in result
                else bundles[result["bundle_id"]]["enhancement_ids"]
            )
        ]
        table = rolltable_builder.build_rolltable(
            pool,
            set_id=set_id,
            module_id=MODULE_ID,
            catalog_pack=CATALOG_PACK,
            enhancements=enhancements,
            catalog_ids=combined_catalog_ids,
            bundles=bundles,
        )
        tables.append(table)
        enhancer_id = enhancement_builder.stable_id(
            f"{set_id}:enhancer", pool["id"]
        )
        enhancers.append(
            consumable_builder.build_enchantment_consumable(
                pool,
                selected,
                set_id=set_id,
                module_id=MODULE_ID,
                table_pack=TABLES_PACK,
                table_id=table["_id"],
                document_id=enhancer_id,
                schema_version=schema_version,
                bundles=bundles,
            )
        )

    documents = {
        ENHANCERS_PACK: enhancers,
        CATALOG_PACK: catalog,
        TABLES_PACK: tables,
    }
    report = {
        "schema_version": schema_version,
        "set": deepcopy(set_data),
        "module_id": MODULE_ID,
        "packs": {
            ENHANCERS_PACK: len(enhancers),
            CATALOG_PACK: len(catalog),
            TABLES_PACK: len(tables),
        },
        "groups": len(validated["groups"]),
        "enhancements": len(enhancements),
        "bundles": len(bundles),
        "pools": len(validated["pools"]),
        "warnings": [],
    }
    return documents, report
