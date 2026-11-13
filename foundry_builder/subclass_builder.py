#!/usr/bin/env python3
"""Сборка компактного подкласса в Item Foundry VTT 13 / D&D5e 5.3.3."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from class_builder import (
    ABILITY_KEYS,
    DOCUMENT_ID,
    FOUNDRY_CORE_VERSION,
    DND5E_SYSTEM_VERSION,
    IDENTIFIER,
    SPELLCASTING_PROGRESSIONS,
    BuildReport,
    ClassBuilderError,
    _as_dict,
    _as_list,
    _build_advancement,
    _description,
    _source,
    _stable_id,
    _validate_advancement,
)


def build_subclass(data: dict[str, Any], source: str = "") -> tuple[dict[str, Any], BuildReport]:
    """Нормализовать полный экспорт или собрать компактный JSON подкласса."""
    if not isinstance(data, dict):
        raise ClassBuilderError("Корень подкласса должен быть объектом JSON.")
    report = BuildReport(source=source)

    if data.get("type") == "subclass" and isinstance(data.get("system"), dict):
        result = deepcopy(data)
        system = result["system"]
        identifier = str(system.get("identifier", "")).strip()
        class_identifier = str(system.get("classIdentifier", "")).strip()
        if not IDENTIFIER.fullmatch(identifier) or not IDENTIFIER.fullmatch(class_identifier):
            raise ClassBuilderError("Экспорт подкласса не содержит identifier/classIdentifier.")
        result.setdefault("_id", _stable_id("subclass", class_identifier, identifier))
        if not DOCUMENT_ID.fullmatch(str(result["_id"])):
            raise ClassBuilderError("Некорректный _id подкласса.")
        advancement = system.setdefault("advancement", {})
        _validate_advancement(advancement, report, allow_blank_scale_identifier=True, document_type="subclass")
        report.class_name = str(result.get("name", ""))
        report.identifier = identifier
        report.input_format = "foundry"
        return result, report

    compact = _as_dict(data.get("subclass", data), "subclass")
    if compact.get("type") not in (None, "subclass"):
        raise ClassBuilderError("type подкласса должен быть 'subclass'.")
    name = str(compact.get("name", "")).strip()
    identifier = str(compact.get("identifier", "")).strip().lower()
    class_identifier = str(compact.get("class_identifier", "")).strip()
    if not name:
        raise ClassBuilderError("name: название подкласса обязательно.")
    if not IDENTIFIER.fullmatch(identifier):
        raise ClassBuilderError("identifier: нужны строчные a-z, цифры и дефисы.")
    if not IDENTIFIER.fullmatch(class_identifier):
        raise ClassBuilderError("class_identifier: нужен точный identifier родительского класса.")

    spellcasting = _as_dict(compact.get("spellcasting"), "spellcasting")
    progression = str(spellcasting.get("progression", "none")).lower()
    ability = str(spellcasting.get("ability", "")).lower()
    if progression not in SPELLCASTING_PROGRESSIONS:
        raise ClassBuilderError("spellcasting.progression: неизвестная прогрессия.")
    if ability and ability not in ABILITY_KEYS:
        raise ClassBuilderError("spellcasting.ability: неизвестная характеристика.")

    preparation = deepcopy(_as_dict(spellcasting.get("preparation"), "spellcasting.preparation"))
    preparation.setdefault("formula", "")

    advancement: dict[str, dict[str, Any]] = {}
    forbidden = {"HitPoints", "Subclass", "AbilityScoreImprovement"}
    for index, raw in enumerate(_as_list(compact.get("advancement"), "advancement")):
        entry = _build_advancement(raw, index, identifier)
        if entry["type"] in forbidden:
            raise ClassBuilderError(f"Подкласс не может содержать {entry['type']}.")
        advancement[entry["_id"]] = entry
    _validate_advancement(advancement, report, document_type="subclass")

    result = {
        "_id": str(compact.get("_id") or _stable_id("subclass", class_identifier, identifier)),
        "name": name,
        "type": "subclass",
        "img": str(compact.get("img", "systems/dnd5e/icons/svg/items/subclass.svg")),
        "system": {
            "advancement": advancement,
            "description": _description(compact.get("description")),
            "identifier": identifier,
            "classIdentifier": class_identifier,
            "source": _source(compact.get("source"), compact),
            "spellcasting": {
                "progression": progression,
                "ability": ability,
                "preparation": preparation,
            },
        },
        "effects": _as_list(compact.get("effects"), "effects"),
        "folder": compact.get("folder"),
        "flags": _as_dict(compact.get("flags"), "flags"),
        "_stats": {
            "compendiumSource": None,
            "duplicateSource": None,
            "coreVersion": FOUNDRY_CORE_VERSION,
            "systemId": "dnd5e",
            "systemVersion": DND5E_SYSTEM_VERSION,
        },
        "ownership": _as_dict(compact.get("ownership", {"default": 0}), "ownership"),
    }
    if not DOCUMENT_ID.fullmatch(result["_id"]):
        raise ClassBuilderError("_id подкласса должен состоять из 16 букв или цифр.")
    report.class_name = name
    report.identifier = identifier
    report.input_format = "compact"
    return result, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    result, _ = build_subclass(data, str(args.input))
    output = args.output or args.input.with_name(args.input.stem + "_foundry.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
