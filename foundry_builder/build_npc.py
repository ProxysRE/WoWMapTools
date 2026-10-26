#!/usr/bin/env python3
"""Полная обработка JSON НПС одной командой.

Цепочка:
    actor_builder -> feat_builder -> weapon_builder -> equipment_builder
    -> spell_builder -> consumable_builder -> item_builder
    -> итоговый JSON
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import actor_builder
import consumable_builder
import equipment_builder
import feat_builder
import item_builder
import midi_compat
import project_config
import spell_builder
import weapon_builder


WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class NpcBuildError(Exception):
    """Ошибка, при которой итоговый JSON нельзя безопасно сохранить."""


def _default_input() -> Path:
    candidates = (Path("input/npc.json"), Path("npc.json"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except FileNotFoundError as error:
        raise NpcBuildError(f"Файл не найден: {path}") from error
    except json.JSONDecodeError as error:
        raise NpcBuildError(
            f"Ошибка JSON в {path}, строка {error.lineno}, "
            f"столбец {error.colno}: {error.msg}"
        ) from error
    except OSError as error:
        raise NpcBuildError(f"Не удалось прочитать {path}: {error}") from error

    if not isinstance(data, dict):
        raise NpcBuildError("Корень JSON должен быть объектом.")
    return data


def _safe_filename(value: str) -> str:
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    filename = re.sub(r"\s+", " ", filename)
    if not filename:
        filename = "Безымянный НПС"
    if filename.upper() in WINDOWS_RESERVED_FILENAMES:
        filename = f"_{filename}"
    return filename


def _default_output(actor: dict[str, Any]) -> Path:
    name = _safe_filename(str(actor.get("name") or "Безымянный НПС"))
    return Path("output/actors") / f"{name}_foundry.json"


def _atomic_json_write(path: Path, data: Any, indent: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(data, temporary, ensure_ascii=False, indent=indent)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except OSError as error:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise NpcBuildError(f"Не удалось записать {path}: {error}") from error


def build_npc(
    source: dict[str, Any],
    source_name: str = "",
    infer_resources: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Последовательно обрабатывает актёра и его вложенные предметы."""
    source_contract = midi_compat.audit_source_document(source)
    if source_contract["errors"]:
        details = "; ".join(source_contract["errors"][:5])
        if len(source_contract["errors"]) > 5:
            details += (
                f"; и ещё {len(source_contract['errors']) - 5} ошибок"
            )
        raise NpcBuildError(
            "Исходный JSON не прошёл смысловую проверку: " + details
        )
    try:
        actor, actor_report = actor_builder.normalize_actor(
            source,
            source_name=source_name,
            infer_resources=infer_resources,
        )
        actor, feat_report, feat_kind = feat_builder.normalize_document(
            actor,
            source_name=source_name,
        )
        actor, weapon_report, weapon_kind = weapon_builder.normalize_document(
            actor,
            source_name=source_name,
        )
        actor, equipment_report, equipment_kind = (
            equipment_builder.normalize_document(
                actor,
                source_name=source_name,
            )
        )
        actor, spell_report, spell_kind = spell_builder.normalize_document(
            actor,
            source_name=source_name,
        )
        actor, consumable_report, consumable_kind = (
            consumable_builder.normalize_document(actor, source_name=source_name)
        )
        actor, item_report, item_kind = item_builder.normalize_document(
            actor, source_name=source_name
        )
    except (
        actor_builder.ActorBuilderError,
        consumable_builder.ConsumableBuilderError,
        equipment_builder.EquipmentBuilderError,
        feat_builder.FeatBuilderError,
        item_builder.ItemBuilderError,
        spell_builder.SpellBuilderError,
        weapon_builder.WeaponBuilderError,
    ) as error:
        raise NpcBuildError(str(error)) from error

    if (
        feat_kind != "actor"
        or weapon_kind != "actor"
        or equipment_kind != "actor"
        or spell_kind != "actor"
        or consumable_kind != "actor"
        or item_kind != "actor"
    ):
        raise NpcBuildError("Внутренняя ошибка: один из модулей вернул не актёра.")

    project_config.normalize_export_versions(actor)
    compatibility = midi_compat.audit_document(actor)
    if compatibility["errors"]:
        details = "; ".join(compatibility["errors"][:5])
        if len(compatibility["errors"]) > 5:
            details += (
                f"; и ещё {len(compatibility['errors']) - 5} ошибок"
            )
        raise NpcBuildError(
            "Итоговый JSON не прошёл проверку Midi-QOL/DAE: " + details
        )

    report = {
        "source": source_name,
        "output": "",
        "actor_name": actor.get("name", "Безымянный НПС"),
        "source_contract": source_contract,
        "pipeline": [
            "actor_builder",
            "feat_builder",
            "weapon_builder",
            "equipment_builder",
            "spell_builder",
            "consumable_builder",
            "item_builder",
        ],
        "actor_builder": asdict(actor_report),
        "feat_builder": asdict(feat_report),
        "weapon_builder": asdict(weapon_report),
        "equipment_builder": asdict(equipment_report),
        "spell_builder": asdict(spell_report),
        "consumable_builder": asdict(consumable_report),
        "item_builder": asdict(item_report),
        "midi_compatibility": compatibility,
    }
    return actor, report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Полностью обрабатывает JSON NPC для Foundry VTT 13.351 / "
            "D&D5e 5.3.3 одной командой."
        )
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=None,
        help="Исходный JSON. По умолчанию: input/npc.json или npc.json.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=(
            "Итоговый JSON. По умолчанию: "
            "output/actors/<имя НПС>_foundry.json."
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("logs/build_npc_report.json"),
        help="Общий JSON-отчёт всех этапов.",
    )
    parser.add_argument(
        "--no-infer-resources",
        action="store_true",
        help="Не создавать легендарные ресурсы по особенностям.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        choices=range(1, 9),
        metavar="1-8",
        help="Отступ в итоговом JSON (по умолчанию: 2).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    source_path = args.source or _default_input()

    try:
        source = _load_json(source_path)
        actor, report = build_npc(
            source,
            source_name=str(source_path),
            infer_resources=not args.no_infer_resources,
        )
        output_path = args.output or _default_output(actor)
        report["output"] = str(output_path)

        # Итог записывается только после успешного завершения всех этапов.
        _atomic_json_write(output_path, actor, args.indent)
        _atomic_json_write(args.report, report, args.indent)
    except NpcBuildError as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return 1

    feat_counts: dict[str, int] = {}
    for feat in report["feat_builder"]["feats"]:
        status = feat["status"]
        feat_counts[status] = feat_counts.get(status, 0) + 1

    weapon_counts: dict[str, int] = {}
    for weapon in report["weapon_builder"]["weapons"]:
        status = weapon["status"]
        weapon_counts[status] = weapon_counts.get(status, 0) + 1

    spell_counts: dict[str, int] = {}
    for spell in report["spell_builder"]["spells"]:
        status = spell["status"]
        spell_counts[status] = spell_counts.get(status, 0) + 1

    equipment_counts: dict[str, int] = {}
    for equipment in report["equipment_builder"]["equipment"]:
        status = equipment["status"]
        equipment_counts[status] = equipment_counts.get(status, 0) + 1

    consumable_counts: dict[str, int] = {}
    for consumable in report["consumable_builder"]["consumables"]:
        status = consumable["status"]
        consumable_counts[status] = consumable_counts.get(status, 0) + 1

    warning_count = sum(
        len(report[key]["warnings"])
        for key in (
            "actor_builder",
            "feat_builder",
            "weapon_builder",
            "equipment_builder",
            "spell_builder",
            "consumable_builder",
            "item_builder",
        )
    )
    warning_count += len(report["midi_compatibility"]["warnings"])

    print(f"Готово: {actor.get('name', 'Безымянный НПС')}")
    print(f"JSON: {output_path}")
    print(f"Отчёт: {args.report}")
    print(
        "Этапы: actor_builder -> feat_builder -> weapon_builder "
        "-> equipment_builder -> spell_builder -> consumable_builder "
        "-> item_builder -> midi_compatibility"
    )
    print(
        f"Исправлений уровня актёра: "
        f"{len(report['actor_builder']['changes'])}"
    )
    if feat_counts:
        summary = ", ".join(
            f"{key}: {value}" for key, value in sorted(feat_counts.items())
        )
        print(f"Особенности: {summary}")
    if weapon_counts:
        summary = ", ".join(
            f"{key}: {value}" for key, value in sorted(weapon_counts.items())
        )
        print(f"Оружие: {summary}")
    if equipment_counts:
        summary = ", ".join(
            f"{key}: {value}"
            for key, value in sorted(equipment_counts.items())
        )
        print(f"Экипировка: {summary}")
    if spell_counts:
        summary = ", ".join(
            f"{key}: {value}" for key, value in sorted(spell_counts.items())
        )
        print(f"Заклинания: {summary}")
    if consumable_counts:
        summary = ", ".join(
            f"{key}: {value}" for key, value in sorted(consumable_counts.items())
        )
        print(f"Расходники: {summary}")
    if report["item_builder"]["items"]:
        print(f"Обычные предметы: {len(report['item_builder']['items'])}")
    print(
        "Midi-QOL/DAE: "
        f"{report['midi_compatibility']['activities']} activities, "
        f"{report['midi_compatibility']['effects']} Active Effects, "
        "структурных ошибок нет"
    )
    if warning_count:
        print(f"Предупреждений: {warning_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
