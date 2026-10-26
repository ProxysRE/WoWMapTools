#!/usr/bin/env python3
"""Сборка RollTable для пула усилений."""

from __future__ import annotations

import html
from typing import Any

from enhancement_builder import ID_PATTERN, MODULE_ID, stable_id
import project_config


class RollTableBuilderError(Exception):
    """Пул нельзя безопасно превратить в RollTable."""


def validate_ranges(
    results: Any,
    *,
    domain: tuple[int, int] = (1, 100),
    path: str = "$.results",
) -> list[dict[str, Any]]:
    if not isinstance(results, list) or not results:
        raise RollTableBuilderError(f"{path} должен быть непустым массивом.")
    normalized: list[dict[str, Any]] = []
    expected = domain[0]
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(results):
        result_path = f"{path}[{index}]"
        if not isinstance(raw, dict):
            raise RollTableBuilderError(f"{result_path} должен быть объектом.")
        unknown = sorted(set(raw) - {"range", "enhancement_id", "bundle_id"})
        if unknown:
            raise RollTableBuilderError(
                f"{result_path} содержит неподдерживаемые поля: "
                + ", ".join(unknown)
                + "."
            )
        bounds = raw.get("range")
        if (
            not isinstance(bounds, list)
            or len(bounds) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in bounds)
        ):
            raise RollTableBuilderError(
                f"{result_path}.range должен иметь вид [1, 40]."
            )
        start, end = bounds
        if start != expected:
            raise RollTableBuilderError(
                f"{result_path}.range начинается с {start}, ожидалось {expected}."
            )
        if end < start or end > domain[1]:
            raise RollTableBuilderError(f"{result_path}.range имеет неверные границы.")
        reference_fields = [
            field
            for field in ("enhancement_id", "bundle_id")
            if str(raw.get(field) or "").strip()
        ]
        if len(reference_fields) != 1:
            raise RollTableBuilderError(
                f"{result_path} должен содержать ровно одну ссылку: "
                "enhancement_id или bundle_id."
            )
        reference_field = reference_fields[0]
        reference_id = str(raw.get(reference_field) or "").strip()
        if not ID_PATTERN.fullmatch(reference_id):
            raise RollTableBuilderError(
                f"{result_path}.{reference_field} должен соответствовать "
                "[a-z][a-z0-9_]{2,63}."
            )
        reference = (reference_field, reference_id)
        if reference in seen:
            raise RollTableBuilderError(
                f"{result_path}: профиль {reference_id} указан повторно."
            )
        seen.add(reference)
        normalized.append({"range": [start, end], reference_field: reference_id})
        expected = end + 1
    if expected != domain[1] + 1:
        raise RollTableBuilderError(
            f"{path} не покрывает значения {expected}–{domain[1]}."
        )
    return normalized


def build_rolltable(
    pool: dict[str, Any],
    *,
    set_id: str,
    module_id: str,
    catalog_pack: str,
    enhancements: dict[str, dict[str, Any]],
    catalog_ids: dict[str, str],
    bundles: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    roll = pool.get("roll")
    if not isinstance(roll, dict):
        raise RollTableBuilderError("$.pool.roll должен быть объектом.")
    formula = str(roll.get("formula") or "")
    domain = roll.get("domain")
    if formula != "1d100" or domain != [1, 100]:
        raise RollTableBuilderError(
            "$.pool.roll должен быть 1d100 с domain [1, 100]."
        )
    results = validate_ranges(pool.get("results"))
    bundles = bundles or {}
    table_id = stable_id(f"{set_id}:table", str(pool["id"]))
    table_results: list[dict[str, Any]] = []
    for result in results:
        reference_field = (
            "enhancement_id" if "enhancement_id" in result else "bundle_id"
        )
        reference_id = result[reference_field]
        catalog_key = (
            reference_id
            if reference_field == "enhancement_id"
            else f"bundle:{reference_id}"
        )
        profile = (
            enhancements.get(reference_id)
            if reference_field == "enhancement_id"
            else bundles.get(reference_id)
        )
        if profile is None or catalog_key not in catalog_ids:
            raise RollTableBuilderError(
                f"Результат ссылается на неизвестный профиль {reference_id}."
            )
        start, end = result["range"]
        catalog_id = catalog_ids[catalog_key]
        if reference_field == "enhancement_id":
            group_description = (
                f"<p><strong>Группа:</strong> "
                f"{html.escape(profile['group'])}; "
                f"<strong>тир:</strong> T{profile['tier']}.</p>"
            )
            result_metadata = {
                "enhancementId": reference_id,
                "group": profile["group"],
                "tier": profile["tier"],
            }
        else:
            groups = [
                enhancements[enhancement_id]["group"]
                for enhancement_id in profile["enhancement_ids"]
            ]
            group_description = (
                f"<p><strong>Составное усиление:</strong> "
                f"{len(profile['enhancement_ids'])} независимых компонентов; "
                f"<strong>тир:</strong> T{profile['tier']}.</p>"
            )
            result_metadata = {
                "bundleId": reference_id,
                "enhancementIds": list(profile["enhancement_ids"]),
                "groups": groups,
                "tier": profile["tier"],
            }
        table_results.append(
            {
                "_id": stable_id(
                    f"{set_id}:{pool['id']}:result",
                    f"{reference_field}:{reference_id}",
                ),
                "type": "document",
                "name": profile["name"],
                "description": (
                    f"<p>{html.escape(profile['description'])}</p>"
                    f"{group_description}"
                ),
                "img": profile["img"],
                "weight": end - start + 1,
                "range": [start, end],
                "drawn": False,
                "documentUuid": (
                    f"Compendium.{module_id}.{catalog_pack}.Item.{catalog_id}"
                ),
                "flags": {
                    MODULE_ID: {
                        "result": result_metadata
                    }
                },
            }
        )
    return {
        "_id": table_id,
        "name": str(pool["name"]),
        "img": "icons/svg/d20-grey.svg",
        "description": (
            f"<p>Таблица пула «{html.escape(str(pool['name']))}». "
            "Бросок не расходует усилитель.</p>"
        ),
        "results": table_results,
        "replacement": True,
        "displayRoll": True,
        "folder": None,
        "sort": 0,
        "ownership": {"default": 0},
        "flags": {
            MODULE_ID: {
                "table": {
                    "setId": set_id,
                    "poolId": str(pool["id"]),
                    "tier": int(pool["tier"]),
                }
            }
        },
        "_stats": {
            "coreVersion": project_config.EXPORT_CORE_VERSION,
            "systemId": None,
            "systemVersion": None,
            "createdTime": 0,
            "modifiedTime": 0,
            "lastModifiedBy": None,
        },
        "formula": formula,
    }
