#!/usr/bin/env python3
"""Сборка обычных предметов (loot) Foundry VTT 13.351 / D&D5e 5.3.3."""

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

import equipment_builder as common
import project_config


ROOT = Path(__file__).resolve().parent

TYPE_ALIASES = {
    "": "",
    "treasure": "treasure",
    "сокровище": "treasure",
    "gear": "gear",
    "снаряжение": "gear",
    "junk": "junk",
    "хлам": "junk",
    "material": "material",
    "материал": "material",
}


class ItemBuilderError(Exception):
    """Ошибка, из-за которой безопасная обработка невозможна."""


@dataclass
class Change:
    path: str
    action: str
    old: Any = None
    new: Any = None


@dataclass
class ItemResult:
    name: str
    item_type: str
    quantity: int | float
    message: str


@dataclass
class BuildReport:
    source: str
    output: str = ""
    changes: list[Change] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    items: list[ItemResult] = field(default_factory=list)

    def change(self, path: str, action: str, old: Any, new: Any) -> None:
        self.changes.append(Change(path, action, old, new))

    def warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


def _load_template() -> dict[str, Any]:
    try:
        value = common.load_template("item")
    except common.EquipmentBuilderError as error:
        raise ItemBuilderError(
            f"Не удалось прочитать шаблон обычного предмета: {error}"
        ) from error
    return value


def _partial_item(source: dict[str, Any]) -> dict[str, Any]:
    item = deepcopy(_load_template())
    item["name"] = str(source.get("name") or "Безымянный предмет")
    if source.get("img") not in (None, ""):
        item["img"] = str(source["img"])
    if isinstance(source.get("system"), dict):
        common._deep_merge(item["system"], source["system"])
    for key in (
        "container", "description", "identified", "identifier", "price",
        "properties", "quantity", "rarity", "source", "unidentified",
        "weight",
    ):
        if key in source:
            item["system"][key] = deepcopy(source[key])
    if source.get("item_type") is not None:
        item["system"]["type"] = deepcopy(source["item_type"])
    if isinstance(source.get("flags"), dict):
        item["flags"] = deepcopy(source["flags"])
    item["type"] = "loot"
    return item


def _normalize_item(item: dict[str, Any], report: BuildReport, path: str) -> None:
    name = str(item.get("name") or "").strip() or "Безымянный предмет"
    item["name"] = name
    item["type"] = "loot"
    common._default(item, "img", "systems/dnd5e/icons/svg/items/loot.svg", report, path)
    common._default(item, "effects", [], report, path)
    common._default(item, "folder", None, report, path)
    common._default(item, "flags", {}, report, path)
    common._default(
        item, "_stats",
        {
            "coreVersion": project_config.EXPORT_CORE_VERSION, "systemId": "dnd5e",
            "systemVersion": project_config.DND5E_VERSION,
            "createdTime": 0, "modifiedTime": 0,
            "lastModifiedBy": None, "exportSource": None,
        },
        report, path,
    )
    system = common._ensure_dict(item, "system", report, path)
    description = system.get("description")
    if isinstance(description, str):
        system["description"] = {"value": description, "chat": ""}
    description = common._ensure_dict(system, "description", report, f"{path}.system")
    common._default(description, "value", "", report, f"{path}.system.description")
    common._default(description, "chat", "", report, f"{path}.system.description")
    common._default(system, "identifier", common._slug(name), report, f"{path}.system")
    common._default(system, "identified", True, report, f"{path}.system")
    common._default(system, "container", None, report, f"{path}.system")
    common._default(system, "quantity", 1, report, f"{path}.system")
    common._default(system, "rarity", "", report, f"{path}.system")
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
        system["type"] = {"value": type_data, "subtype": ""}
    type_data = common._ensure_dict(system, "type", report, f"{path}.system")
    raw_type = str(type_data.get("value") or "")
    type_data["value"] = TYPE_ALIASES.get(
        raw_type.casefold().replace("ё", "е").strip(), raw_type
    )
    common._default(type_data, "subtype", "", report, f"{path}.system.type")
    report.items.append(
        ItemResult(name, type_data["value"], system["quantity"], "Предмет нормализован.")
    )


def normalize_document(
    source: dict[str, Any], source_name: str = ""
) -> tuple[dict[str, Any], BuildReport, str]:
    if not isinstance(source, dict):
        raise ItemBuilderError("Корень JSON должен быть объектом.")
    report = BuildReport(source=source_name)
    document_type = source.get("type")
    is_actor = document_type == "npc" or (
        isinstance(source.get("items"), list)
        and isinstance(source.get("system"), dict)
        and document_type != "loot"
    )
    if is_actor:
        document = deepcopy(source)
        items = document.get("items")
        if not isinstance(items, list):
            raise ItemBuilderError("У актёра items должен быть массивом.")
        for index, item in enumerate(items):
            if isinstance(item, dict) and item.get("type") == "loot":
                if not isinstance(item.get("system"), dict):
                    item = _partial_item(item)
                    items[index] = item
                _normalize_item(item, report, f"$.items[{index}]")
        return document, report, "actor"
    document = (
        deepcopy(source)
        if document_type == "loot" and isinstance(source.get("system"), dict)
        else _partial_item(source)
    )
    _normalize_item(document, report, "$")
    return document, report, "loot"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            value = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise ItemBuilderError(f"Не удалось прочитать {path}: {error}") from error
    if not isinstance(value, dict):
        raise ItemBuilderError("Корень JSON должен быть объектом.")
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
        raise ItemBuilderError(f"Не удалось записать {path}: {error}") from error


def _safe_filename(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .") or "Предмет"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Собирает обычные предметы Foundry VTT.")
    parser.add_argument("source", nargs="?", type=Path, default=Path("input/item.json"))
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--report", type=Path, default=Path("logs/item_builder_report.json"))
    parser.add_argument("--indent", type=int, default=2, choices=range(1, 9))
    args = parser.parse_args(argv)
    try:
        source = _load_json(args.source)
        document, report, kind = normalize_document(source, str(args.source))
        folder = "actors" if kind == "actor" else "items"
        output = args.output or Path("output") / folder / (
            f"{_safe_filename(str(document.get('name') or 'Предмет'))}_foundry.json"
        )
        report.output = str(output)
        _atomic_json_write(output, document, args.indent)
        _atomic_json_write(args.report, asdict(report), args.indent)
    except ItemBuilderError as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return 1
    print(f"Готово: {output}")
    print(f"Предметов: {len(report.items)}; предупреждений: {len(report.warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
