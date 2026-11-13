#!/usr/bin/env python3
"""Предыстории D&D5e 5.3.3: нативные документы и компактные исходники."""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from class_builder import (
    ClassBuilderError, BuildReport, DOCUMENT_ID, IDENTIFIER, _as_dict,
    _as_list, _build_advancement, _description, _source, _stable_id,
    _validate_advancement,
)
import project_config


def build_background(data: dict[str, Any], source: str = "") -> tuple[dict, BuildReport]:
    if not isinstance(data, dict):
        raise ClassBuilderError("Предыстория должна быть объектом JSON.")
    report = BuildReport(source=source)
    native = data.get("type") == "background" and isinstance(data.get("system"), dict)
    raw = _as_dict(data.get("background", data), "background")
    system = raw["system"] if native else raw
    if raw.get("type") not in (None, "background"):
        raise ClassBuilderError("type предыстории должен быть background.")
    name = str(raw.get("name", "")).strip()
    identifier = str(system.get("identifier", "")).strip()
    if not name or not IDENTIFIER.fullmatch(identifier):
        raise ClassBuilderError("Предыстория требует name и корректный identifier.")
    if native:
        result = deepcopy(raw)
        advancement = _as_dict(system.get("advancement", {}), "advancement")
        result["system"]["advancement"] = deepcopy(advancement)
    else:
        advancement = {}
        for index, entry in enumerate(_as_list(raw.get("advancement"), "advancement")):
            built = _build_advancement(entry, index, identifier, minimum_level=0)
            if built["_id"] in advancement:
                raise ClassBuilderError("Повтор advancement _id предыстории.")
            advancement[built["_id"]] = built
        result = {
            "name": name, "type": "background",
            "img": raw.get("img", "systems/dnd5e/icons/svg/items/background.svg"),
            "system": {
                "identifier": identifier, "description": _description(raw.get("description")),
                "source": _source(raw.get("source"), raw), "advancement": advancement,
                "startingEquipment": deepcopy(_as_list(raw.get("starting_equipment", raw.get("startingEquipment")), "starting_equipment")),
            },
            "effects": deepcopy(_as_list(raw.get("effects"), "effects")),
            "flags": deepcopy(_as_dict(raw.get("flags"), "flags")),
            "folder": raw.get("folder"), "ownership": deepcopy(raw.get("ownership", {"default": 0})),
        }
    result.setdefault("_id", _stable_id("background", identifier))
    if not DOCUMENT_ID.fullmatch(str(result["_id"])):
        raise ClassBuilderError("_id предыстории должен состоять из 16 букв/цифр.")
    _validate_advancement(result["system"]["advancement"], report, document_type="background")
    for entry in result["system"]["advancement"].values():
        if entry.get("level", 0) != 0:
            raise ClassBuilderError("Развитие предыстории должно иметь уровень 0.")
    result.setdefault("_stats", {"coreVersion": project_config.EXPORT_CORE_VERSION,
                                "systemId": "dnd5e", "systemVersion": project_config.DND5E_VERSION})
    project_config.normalize_export_versions(result)
    report.class_name, report.identifier = name, identifier
    report.input_format = "foundry" if native else "compact"
    return result, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    result, _ = build_background(json.loads(args.input.read_text(encoding="utf-8-sig")), str(args.input))
    target = args.output or args.input.with_name(args.input.stem + "_foundry.json")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
