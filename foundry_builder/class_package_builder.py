#!/usr/bin/env python3
"""Упаковщик класса, подкласса и особенностей в переносимый JSON-каталог."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import zipfile
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

from class_builder import ClassBuilderError, IDENTIFIER, DOCUMENT_ID, _stable_id, _build_advancement, _validate_advancement, BuildReport, build_class
from race_builder import build_race
from background_builder import build_background
import project_config
from package_validation import validate_documents
from subclass_builder import build_subclass


_FEAT_BUILDER = None
AUTOMATION_MODES = {"full", "partial", "manual", "passive"}


def _load_feat_builder():
    global _FEAT_BUILDER
    if _FEAT_BUILDER is not None:
        return _FEAT_BUILDER
    path = Path(__file__).resolve().parent / "feat_builder.py"
    if not path.is_file():
        raise ClassBuilderError(
            "Не найден локальный feat_builder.py. "
            "Экспериментальный проект должен быть самодостаточным."
        )
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("_pc_feat_builder", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _FEAT_BUILDER = module
    return _FEAT_BUILDER


def _feature_item(
    raw: dict[str, Any],
    package_identifier: str,
    *,
    require_automation_contract: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    key = str(raw.get("key", "")).strip()
    name = str(raw.get("name", "")).strip()
    if not key.startswith(("feature:", "feat:")) or not name:
        raise ClassBuilderError("Каждая особенность требует key вида feature:... или feat:... и name.")
    identifier = key.split(":", 1)[1]
    if not IDENTIFIER.fullmatch(identifier):
        raise ClassBuilderError(f"Некорректный ключ особенности: {key}.")
    activities: dict[str, Any] = {}
    for index, activity in enumerate(raw.get("activities", [])):
        activity_id = _stable_id(package_identifier, key, "activity", index)
        activities[activity_id] = deepcopy(activity)
        activities[activity_id]["_id"] = activity_id
    flags = deepcopy(raw.get("flags", {}))
    if not isinstance(flags, dict):
        flags = {}
    generator_flags = flags.setdefault("foundry-content-generator", {})
    if not isinstance(generator_flags, dict):
        generator_flags = {}
        flags["foundry-content-generator"] = generator_flags

    uses = deepcopy(raw.get("uses", {"spent": 0, "recovery": []}))
    resource_pool = raw.get("resource_pool")
    if isinstance(resource_pool, dict):
        pool_key = str(resource_pool.get("key") or "").strip()
        pool_max = str(resource_pool.get("max") or "").strip()
        if not pool_key or not pool_max:
            raise ClassBuilderError(
                f"{name}: resource_pool требует непустые key и max."
            )
        recovery = resource_pool.get("recovery", [])
        if not isinstance(recovery, list):
            raise ClassBuilderError(
                f"{name}: resource_pool.recovery должен быть массивом."
            )
        uses = {
            "max": pool_max,
            "spent": int(resource_pool.get("spent", 0) or 0),
            "recovery": deepcopy(recovery),
        }
        generator_flags["resourcePool"] = {
            "key": pool_key,
            "label": str(resource_pool.get("label") or name),
            "initialEmpty": bool(resource_pool.get("initial_empty", False)),
        }

    automation = raw.get("automation")
    if isinstance(automation, dict):
        generator_flags["automation"] = deepcopy(automation)

    result = {
        "_id": _stable_id(package_identifier, key),
        "name": name,
        "type": "feat",
        "img": raw.get("img", "systems/dnd5e/icons/svg/items/feature.svg"),
        "system": {
            "activities": activities,
            "uses": uses,
            "advancement": {},
            "description": {"value": str(raw.get("description", "")), "chat": ""},
            "identifier": identifier,
            "source": deepcopy(raw.get("source", {"revision": 1, "rules": raw.get("rules", "2024")})),
            "crewed": False,
            "enchant": {},
            "prerequisites": deepcopy(raw.get("prerequisites", {"items": [], "repeatable": False})),
            "properties": list(raw.get("properties", [])),
            "requirements": str(raw.get("requirements", "")),
            "type": {"value": str(raw.get("feature_type", "class")), "subtype": ""},
        },
        "effects": deepcopy(raw.get("effects", [])),
        "folder": None,
        "flags": flags,
        "_stats": {
            "coreVersion": project_config.EXPORT_CORE_VERSION,
            "systemId": "dnd5e",
            "systemVersion": "5.3.3",
        },
        "ownership": {"default": 0},
    }
    if isinstance(raw.get("mechanics"), dict):
        result["mechanics"] = deepcopy(raw["mechanics"])
    advancements = raw.get("advancement", [])
    if not isinstance(advancements, list):
        raise ClassBuilderError(f"{name}: advancement особенности должен быть массивом.")
    for index, advancement in enumerate(advancements):
        entry = _build_advancement(advancement, index, identifier, minimum_level=0)
        if entry["type"] not in {"AbilityScoreImprovement", "Trait", "ItemGrant", "ItemChoice"}:
            raise ClassBuilderError(f"{name}: неподдерживаемое развитие особенности {entry['type']}.")
        if entry["_id"] in result["system"]["advancement"]:
            raise ClassBuilderError(f"{name}: повтор advancement _id.")
        result["system"]["advancement"][entry["_id"]] = entry
    _validate_advancement(result["system"]["advancement"], BuildReport(), document_type="feat")
    feat_builder = _load_feat_builder()
    normalized, builder_report, _ = feat_builder.normalize_document(result, key)
    normalized["_id"] = result["_id"]
    for activity in normalized.get("system", {}).get("activities", {}).values():
        if not activity.get("img"):
            activity["img"] = normalized["img"]
        if not activity.get("name"):
            activity["name"] = normalized["name"]
    for effect in normalized.get("effects", []):
        if not effect.get("img"):
            effect["img"] = normalized["img"]
    automation_report = _audit_feature_automation(
        raw,
        normalized,
        require_contract=require_automation_contract,
    )
    compatibility = feat_builder.midi_compat.audit_document(normalized)
    automation_report["errors"].extend(compatibility["errors"])
    automation_report["warnings"].extend(compatibility["warnings"])
    automation_report["builder_warnings"] = list(builder_report.warnings)
    automation_report["builder_results"] = [
        asdict(item) for item in builder_report.feats
    ]
    return normalized, automation_report


def _audit_feature_automation(
    raw: dict[str, Any],
    normalized: dict[str, Any],
    *,
    require_contract: bool,
) -> dict[str, Any]:
    name = str(raw.get("name") or "Безымянная особенность")
    automation = raw.get("automation")
    errors: list[str] = []
    warnings: list[str] = []
    manual: list[str] = []
    requires: list[str] = []
    mode = ""

    if isinstance(automation, dict):
        mode = str(automation.get("mode") or "").strip().casefold()
        raw_manual = automation.get("manual", [])
        if isinstance(raw_manual, str):
            manual = [raw_manual] if raw_manual.strip() else []
        elif isinstance(raw_manual, list):
            manual = [str(value).strip() for value in raw_manual if str(value).strip()]
        raw_requires = automation.get("requires", [])
        if isinstance(raw_requires, str):
            requires = [raw_requires] if raw_requires.strip() else []
        elif isinstance(raw_requires, list):
            requires = [
                str(value).strip()
                for value in raw_requires
                if str(value).strip()
            ]
    elif require_contract:
        errors.append(
            f"{name}: отсутствует обязательный объект automation для схемы пакета 2."
        )
    else:
        warnings.append(
            f"{name}: старый ввод без automation; полнота автоматизации не заявлена."
        )

    if (require_contract or mode) and mode not in AUTOMATION_MODES:
        errors.append(
            f"{name}: automation.mode должен быть full, partial, manual или passive."
        )

    activities = normalized.get("system", {}).get("activities", {})
    effects = normalized.get("effects", [])
    activity_count = len(activities) if isinstance(activities, dict) else 0
    effect_count = len(effects) if isinstance(effects, list) else 0
    transfer_effects = sum(
        1
        for effect in effects
        if isinstance(effect, dict) and effect.get("transfer")
    )

    if mode == "full" and activity_count == 0 and effect_count == 0:
        errors.append(
            f"{name}: заявлена полная автоматизация, но не создано ни activity, "
            "ни Active Effect."
        )
    if mode in {"partial", "manual"} and not manual:
        errors.append(
            f"{name}: {mode} требует перечислить ручную часть в automation.manual."
        )
    if mode == "manual" and activity_count:
        warnings.append(
            f"{name}: mode=manual, хотя билдер создал {activity_count} activities."
        )
    if mode == "passive" and activity_count:
        errors.append(
            f"{name}: mode=passive несовместим с нажимаемыми activities."
        )

    return {
        "key": str(raw.get("key") or ""),
        "name": name,
        "mode": mode or "legacy",
        "manual": manual,
        "requires": requires,
        "activities": activity_count,
        "effects": effect_count,
        "transfer_effects": transfer_effects,
        "errors": errors,
        "warnings": warnings,
    }


def _replace_refs(document: Any, ref_map: dict[str, str]) -> Any:
    if isinstance(document, dict):
        if "ref" in document:
            ref = str(document.pop("ref"))
            if ref not in ref_map:
                raise ClassBuilderError(f"Не найдена особенность для ссылки {ref}.")
            document["uuid"] = ref_map[ref]
        return {key: _replace_refs(value, ref_map) for key, value in document.items()}
    if isinstance(document, list):
        return [_replace_refs(value, ref_map) for value in document]
    if isinstance(document, str) and document.startswith(("feature:", "feat:", "spell:")):
        if document not in ref_map:
            raise ClassBuilderError(f"Не найдена особенность для ссылки {document}.")
        return ref_map[document]
    return document


def build_package(data: dict[str, Any], base_dir: Path | None = None) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ClassBuilderError("Корень пакета должен быть объектом JSON.")
    data = deepcopy(data)
    base_dir = base_dir or Path.cwd()
    for field in ("class", "subclass", "features", "feats", "spells"):
        if field + "_file" in data:
            if field in data:
                raise ClassBuilderError(f"Заданы одновременно {field} и {field}_file.")
            data[field] = json.loads((base_dir / data[field + "_file"]).read_text(encoding="utf-8-sig"))
    for field in ("subclasses", "races", "backgrounds"):
        file_field = {"subclasses": "subclass_files", "races": "race_files", "backgrounds": "background_files"}[field]
        if file_field in data:
            if field in data or not isinstance(data[file_field], list):
                raise ClassBuilderError(f"Конфликт или неверный тип {file_field}.")
            data[field] = [json.loads((base_dir / filename).read_text(encoding="utf-8-sig")) for filename in data[file_field]]
    if "subclass" in data and "subclasses" in data:
        raise ClassBuilderError("Задайте subclass или subclasses, не оба.")
    raw_subclasses = data.get("subclasses", [data["subclass"]] if "subclass" in data else [])
    raw_races = data.get("races", [])
    raw_backgrounds = data.get("backgrounds", [])
    for label, values in (("subclasses", raw_subclasses), ("races", raw_races), ("backgrounds", raw_backgrounds), ("features", data.get("features", [])), ("feats", data.get("feats", []))):
        if not isinstance(values, list) or any(not isinstance(x, dict) for x in values):
            raise ClassBuilderError(f"{label} должен быть массивом объектов.")
    identifier = str(data.get("identifier", "")).strip()
    if not IDENTIFIER.fullmatch(identifier):
        raise ClassBuilderError("Пакету требуется identifier из a-z, 0-9 и дефисов.")
    schema_version = data.get("schema_version", 1)
    if type(schema_version) is not int or schema_version not in {1, 2, 3, 4}:
        raise ClassBuilderError("schema_version: поддерживаются 1, 2, 3, 4.")
    if schema_version < 4 and any(k in data for k in ("backgrounds", "background_files", "external_classes", "feats", "feats_file")):
        raise ClassBuilderError("Предыстории, внешние классы и общие черты требуют schema_version 4.")
    strict_automation = data.get("strict_automation", schema_version >= 2)
    if not isinstance(strict_automation, bool):
        raise ClassBuilderError("strict_automation должен быть boolean.")
    # Правила хака задаются автором явно; старые пакеты сохраняют свой default.
    if "rules" in data:
        if data["rules"] not in {"2014", "2024"}:
            raise ClassBuilderError("rules: 2014 или 2024.")
        for raw in [data.get("class"), *raw_subclasses, *raw_races, *raw_backgrounds, *data.get("features", []), *data.get("feats", [])]:
            if raw is not None and "system" not in raw:
                raw.setdefault("rules", data["rules"])
    feature_ref_map = {
        str(item.get("key", "")): f"Compendium.{identifier}.features.Item.{_stable_id(identifier, str(item.get('key', '')))}"
        for item in data.get("features", [])
    }
    for item in data.get("feats", []):
        key = str(item.get("key", ""))
        if not key.startswith("feat:"):
            raise ClassBuilderError("Общая черта требует key вида feat:...")
        feature_ref_map[key] = f"Compendium.{identifier}.feats.Item.{_stable_id(identifier, key)}"
    spell_inputs = data.get("spells", [])
    if not isinstance(spell_inputs, list):
        raise ClassBuilderError("spells должен быть массивом полных экспортов spell.")
    spells = []
    spell_reports = []
    for item in spell_inputs:
        if not isinstance(item, dict) or not isinstance(item.get("system"), dict):
            raise ClassBuilderError("spells[]: требуется объект Item spell с system.")
        slug = item["system"].get("identifier")
        if isinstance(slug, str):
            spell_id = item.get("_id") or _stable_id(identifier, "spell", slug)
            feature_ref_map["spell:" + slug] = f"Compendium.{identifier}.spells.Item.{spell_id}"
    for item in spell_inputs:
        if not isinstance(item, dict) or item.get("type") != "spell" or not item.get("system", {}).get("identifier"):
            raise ClassBuilderError("Каждое spells[] должно быть полным Item spell с identifier.")
        if schema_version >= 4:
            import spell_builder
            candidate = _replace_refs(deepcopy(item), feature_ref_map)
            candidate.setdefault("_id", _stable_id(identifier, "spell", item["system"]["identifier"]))
            candidate["system"].setdefault("source", {}).setdefault("rules", data.get("rules", "2014"))
            contract = _load_feat_builder().midi_compat.audit_source_document(candidate)
            if contract["errors"]:
                raise ClassBuilderError("Ошибки исходника заклинания: " + "; ".join(contract["errors"]))
            item, report, _ = spell_builder.normalize_document(candidate)
            from dataclasses import asdict
            spell_reports.append(asdict(report))
            compatibility = _load_feat_builder().midi_compat.audit_document(item)
            if compatibility["errors"]:
                raise ClassBuilderError("Ошибки заклинания: " + "; ".join(compatibility["errors"]))
        if not DOCUMENT_ID.fullmatch(str(item.get("_id", ""))) or not IDENTIFIER.fullmatch(str(item["system"]["identifier"])):
            raise ClassBuilderError("spells[]: некорректный _id или identifier.")
        spells.append(deepcopy(item))
        feature_ref_map["spell:" + item["system"]["identifier"]] = f"Compendium.{identifier}.spells.Item.{item['_id']}"
    feature_results = [
        _feature_item(
            {**_replace_refs({k: deepcopy(v) for k,v in item.items() if k != "key"}, feature_ref_map), "key": item.get("key", "")},
            identifier,
            require_automation_contract=strict_automation,
        )
        for item in [*data.get("features", []), *[dict(f, feature_type=f.get("feature_type", "feat")) for f in data.get("feats", [])]]
    ]
    features = [item for item, _ in feature_results[:len(data.get("features", []))]]
    feats = [item for item, _ in feature_results[len(data.get("features", [])):]]
    feature_reports = [report for _, report in feature_results]
    feature_errors = [
        error
        for report in feature_reports
        for error in report["errors"]
    ]
    declared_pools: dict[str, str] = {}
    consumed_pools: set[str] = set()
    for feature in features + feats:
        generator_flags = (
            feature.get("flags", {}).get("foundry-content-generator", {})
        )
        pool = (
            generator_flags.get("resourcePool")
            if isinstance(generator_flags, dict)
            else None
        )
        if isinstance(pool, dict) and pool.get("key"):
            pool_key = str(pool["key"])
            if pool_key in declared_pools:
                feature_errors.append(
                    f"Общий ресурс «{pool_key}» объявлен одновременно в "
                    f"«{declared_pools[pool_key]}» и «{feature['name']}»."
                )
            declared_pools[pool_key] = str(feature["name"])
        for activity in feature.get("system", {}).get("activities", {}).values():
            activity_pool = (
                activity.get("flags", {})
                .get("foundry-content-generator", {})
                .get("resourcePool")
            )
            if isinstance(activity_pool, dict) and activity_pool.get("key"):
                consumed_pools.add(str(activity_pool["key"]))
    for missing_pool in sorted(consumed_pools - set(declared_pools)):
        feature_errors.append(
            f"Activities расходуют общий ресурс «{missing_pool}», "
            "но ни одна особенность пакета его не объявляет."
        )
    if feature_errors:
        raise ClassBuilderError(
            "Ошибки автоматизации особенностей:\n- "
            + "\n- ".join(feature_errors)
        )
    keys = [str(item.get("key", "")) for item in [*data.get("features", []), *data.get("feats", [])]]
    if len(keys) != len(set(keys)):
        raise ClassBuilderError("Ключи особенностей должны быть уникальны.")
    ref_map = dict(feature_ref_map)
    # Разрешаем также ссылки во вложенных выборах особенностей.
    features = _replace_refs(features, ref_map)
    documents = {"subclasses": [], "races": [], "features": features}
    if schema_version >= 4:
        documents["external_classes"] = data.get("external_classes", [])
        documents["library_spells"] = True
    if feats:
        documents["feats"] = _replace_refs(feats, ref_map)
    if spells:
        documents["spells"] = spells
    class_report = None
    if data.get("class") is not None:
        class_item, class_report = build_class(_replace_refs(deepcopy(data["class"]), ref_map))
        explicit_id = data["class"].get("_id")
        if explicit_id is not None and not DOCUMENT_ID.fullmatch(str(explicit_id)):
            raise ClassBuilderError("class._id: требуется ID из 16 букв/цифр.")
        class_item.setdefault("_id", explicit_id or _stable_id("class", class_item["system"]["identifier"]))
        documents["class"] = class_item
    subclass_reports, race_reports = [], []
    for raw in raw_subclasses:
        item, report = build_subclass(_replace_refs(deepcopy(raw), ref_map))
        documents["subclasses"].append(item)
        subclass_reports.append(report)
    for raw in raw_races:
        item, report = build_race(_replace_refs(deepcopy(raw), ref_map))
        documents["races"].append(item)
        race_reports.append(report)
    background_reports = []
    if raw_backgrounds:
        documents["backgrounds"] = []
    for raw in raw_backgrounds:
        item, report = build_background(_replace_refs(deepcopy(raw), ref_map))
        documents["backgrounds"].append(item)
        background_reports.append(report)
    # Обратная совместимость с пакетами schema 1/2.
    if len(documents["subclasses"]) == 1:
        documents["subclass"] = documents["subclasses"][0]
    validate_documents(documents, identifier)
    project_config.normalize_export_versions(documents)
    return {
        "schema_version": schema_version,
        "package": {
            "identifier": identifier,
            "name": str(data.get("name", identifier)),
            "foundry": project_config.FOUNDRY_VERSION,
            "dnd5e": project_config.DND5E_VERSION,
        },
        "documents": documents,
        "reference_map": ref_map,
        "reports": {
            "class_warnings": class_report.warnings if class_report else [],
            "subclass_warnings": [w for r in subclass_reports for w in r.warnings],
            "race_warnings": [w for r in race_reports for w in r.warnings],
            "background_warnings": [w for r in background_reports for w in r.warnings],
            "spells": spell_reports,
            "features": feature_reports,
            "automation": {
                "strict": strict_automation,
                "full": sum(
                    report["mode"] == "full" for report in feature_reports
                ),
                "partial": sum(
                    report["mode"] == "partial" for report in feature_reports
                ),
                "manual": sum(
                    report["mode"] == "manual" for report in feature_reports
                ),
                "passive": sum(
                    report["mode"] == "passive" for report in feature_reports
                ),
                "legacy": sum(
                    report["mode"] == "legacy" for report in feature_reports
                ),
                "resource_pools": {
                    key: declared_pools[key] for key in sorted(declared_pools)
                },
                "consumed_pools": sorted(consumed_pools),
            },
        },
    }


def write_zip(result: dict[str, Any], target: Path) -> None:
    groups = validate_documents(result["documents"], result["package"]["identifier"])
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(result["package"], ensure_ascii=False, indent=2))
        archive.writestr("package.json", json.dumps(result, ensure_ascii=False, indent=2))
        for pack, items in groups.items():
            for item in items:
                archive.writestr(f"{pack}/{item['_id']}.json", json.dumps(item, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--zip", type=Path)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    result = build_package(source, args.input.parent)
    output = args.output or args.input.with_name(args.input.stem + "_foundry_package.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.zip:
        write_zip(result, args.zip)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
