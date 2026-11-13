#!/usr/bin/env python3
"""Кастомные расы и законченные варианты подрас для dnd5e 5.3.3."""
from __future__ import annotations
import argparse
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any
from class_builder import (
    BuildReport, ClassBuilderError, DOCUMENT_ID, IDENTIFIER,
    FOUNDRY_CORE_VERSION, DND5E_SYSTEM_VERSION, _as_dict, _as_list,
    _build_advancement, _description, _source, _stable_id, _validate_advancement,
)

SIZES = {"tiny", "sm", "med", "lg", "huge", "grg"}
RACE_ADVANCEMENTS = {"Size", "AbilityScoreImprovement", "Trait", "ItemGrant", "ItemChoice"}


def _range(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value or value < 0:
        raise ClassBuilderError(f"{path}: требуется целое неотрицательное число.")
    return int(value)


def _validate(document: dict[str, Any], report: BuildReport) -> None:
    if not DOCUMENT_ID.fullmatch(str(document.get("_id", ""))):
        raise ClassBuilderError("Некорректный _id расы.")
    if not str(document.get("name", "")).strip():
        raise ClassBuilderError("name расы обязательно.")
    system = document["system"]
    if not IDENTIFIER.fullmatch(str(system.get("identifier", ""))):
        raise ClassBuilderError("identifier расы: нужны строчные a-z, цифры и дефисы.")
    advancement = system.get("advancement", {})
    if not isinstance(advancement, dict):
        raise ClassBuilderError("system.advancement расы должен быть объектом.")
    for key, entry in advancement.items():
        if not isinstance(entry, dict) or entry.get("type") not in RACE_ADVANCEMENTS:
            raise ClassBuilderError(f"Недопустимое развитие расы: {key}.")
        if entry["type"] == "Size":
            sizes = entry.get("configuration", {}).get("sizes", [])
            if not isinstance(sizes, list) or not sizes or any(not isinstance(s, str) or s not in SIZES for s in sizes):
                raise ClassBuilderError("Size требует непустой список допустимых размеров.")
    if sum(e["type"] == "Size" for e in advancement.values()) != 1:
        raise ClassBuilderError("Раса должна содержать ровно один Size advancement.")
    _validate_advancement(advancement, report, document_type="race")
    movement = system.get("movement", {})
    if not isinstance(movement, dict) or movement.get("units") not in {"ft", "m"}:
        raise ClassBuilderError("movement.units расы: ft или m.")
    for key in ("walk", "burrow", "climb", "fly", "swim"):
        _range(movement.get(key, 0), f"movement.{key}")
    senses = system.get("senses", {})
    if not isinstance(senses, dict) or senses.get("units") not in {"ft", "m"}:
        raise ClassBuilderError("senses.units расы: ft или m.")
    ranges = senses.get("ranges", {})
    if not isinstance(ranges, dict) or set(ranges) - {"darkvision", "blindsight", "tremorsense", "truesight"}:
        raise ClassBuilderError("Неизвестные senses.ranges расы.")
    for key, value in ranges.items():
        if value is not None:
            _range(value, f"senses.ranges.{key}")
    if not isinstance(system.get("type"), dict) or not system["type"].get("value"):
        raise ClassBuilderError("Раса требует creature_type / system.type.value.")


def build_race(data: dict[str, Any], source: str = "") -> tuple[dict[str, Any], BuildReport]:
    if not isinstance(data, dict):
        raise ClassBuilderError("Корень расы должен быть объектом.")
    report = BuildReport(source=source)
    if data.get("type") == "race" and isinstance(data.get("system"), dict):
        result = deepcopy(data)
        # Foundry world exports can omit the root _id and use null units to
        # inherit the world defaults. The portable target uses explicit feet.
        identifier = str(result.get("system", {}).get("identifier", ""))
        if not DOCUMENT_ID.fullmatch(str(result.get("_id", ""))):
            result["_id"] = _stable_id("race", identifier)
        movement = _as_dict(result["system"].get("movement"), "system.movement")
        result["system"]["movement"] = movement
        movement["units"] = movement.get("units") or "ft"
        for key in ("walk", "burrow", "climb", "fly", "swim"):
            value = movement.get(key, 0)
            if value is None:
                value = 0
            if isinstance(value, str):
                try:
                    numeric = float(value)
                    if not math.isfinite(numeric) or not numeric.is_integer():
                        raise ValueError
                    value = int(numeric)
                except ValueError:
                    raise ClassBuilderError(f"movement.{key}: требуется целое расстояние.")
            movement[key] = value
        senses = _as_dict(result["system"].get("senses"), "system.senses")
        result["system"]["senses"] = senses
        senses["units"] = senses.get("units") or movement["units"]
        senses.setdefault("ranges", {})
        report.input_format = "foundry"
    else:
        raw = _as_dict(data.get("race", data), "race")
        if raw.get("type") not in (None, "race"):
            raise ClassBuilderError("type расы должен быть race.")
        identifier = str(raw.get("identifier", "")).strip()
        if not IDENTIFIER.fullmatch(identifier):
            raise ClassBuilderError("identifier расы: нужны строчные a-z, цифры и дефисы.")
        entries = _as_list(raw.get("advancement"), "advancement")
        if not any(e.get("type", "").lower() == "size" for e in entries):
            entries.insert(0, {"type": "Size", "sizes": raw.get("sizes", ["med"])})
        advancement = {}
        for index, entry in enumerate(entries):
            entry = deepcopy(entry)
            entry.setdefault("level", 0)
            built = _build_advancement(entry, index, identifier, minimum_level=0)
            if built["_id"] in advancement:
                raise ClassBuilderError("Повторяющийся advancement _id расы.")
            advancement[built["_id"]] = built
        movement = {k: 0 for k in ("walk", "burrow", "climb", "fly", "swim")}
        movement.update({"walk": 30, "units": "ft", "hover": False, "ignoredDifficultTerrain": []})
        movement.update(_as_dict(raw.get("movement"), "movement"))
        senses = {"ranges": {}, "units": movement["units"], "special": ""}
        senses.update(_as_dict(raw.get("senses"), "senses"))
        result = {
            "_id": str(raw.get("_id") or _stable_id("race", identifier)),
            "name": str(raw.get("name", "")).strip(), "type": "race",
            "img": str(raw.get("img", "icons/environment/people/group.webp")),
            "system": {"identifier": identifier, "description": _description(raw.get("description")),
                       "source": _source(raw.get("source"), raw), "advancement": advancement,
                       "movement": movement, "senses": senses,
                       "type": _as_dict(raw.get("creature_type", {"value": "humanoid", "custom": "", "subtype": ""}), "creature_type")},
            "effects": _as_list(raw.get("effects"), "effects"), "folder": None,
            "flags": _as_dict(raw.get("flags"), "flags"), "ownership": {"default": 0},
            "_stats": {"coreVersion": FOUNDRY_CORE_VERSION, "systemId": "dnd5e", "systemVersion": DND5E_SYSTEM_VERSION},
        }
        if raw.get("parent_identifier"):
            parent = str(raw["parent_identifier"])
            if not IDENTIFIER.fullmatch(parent):
                raise ClassBuilderError("Некорректный parent_identifier подрасы.")
            result["flags"].setdefault("foundry-content-generator", {})["parentRace"] = parent
        report.input_format = "compact"
    _validate(result, report)
    report.class_name = result["name"]
    report.identifier = result["system"]["identifier"]
    return result, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    result, _ = build_race(json.loads(args.input.read_text(encoding="utf-8-sig")), str(args.input))
    target = args.output or args.input.with_name(args.input.stem + "_foundry.json")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
