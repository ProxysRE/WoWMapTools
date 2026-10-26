#!/usr/bin/env python3
"""Сборка устанавливаемого модуля с паками усилений."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import enhancement_set_builder
import project_config


ROOT = Path(__file__).resolve().parent
MODULE_ID = enhancement_set_builder.MODULE_ID
COMPENDIUM_FOLDER = "Усиления"
RUNTIME_SCRIPT = (
    ROOT
    / "runtime"
    / MODULE_ID
    / "scripts"
    / "enhancement-groups.mjs"
)


class EnhancementModuleBuildError(Exception):
    """Устанавливаемый модуль не удалось собрать."""


def _prepare_pack_document(
    document: dict[str, Any],
    collection: str,
) -> dict[str, Any]:
    prepared = copy.deepcopy(document)
    document_id = prepared["_id"]
    prepared["_key"] = f"!{collection}!{document_id}"
    embedded_collection = "results" if collection == "tables" else "effects"
    for embedded in prepared.get(embedded_collection, []):
        embedded["_key"] = (
            f"!{collection}.{embedded_collection}!"
            f"{document_id}.{embedded['_id']}"
        )
    return prepared


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            value = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise EnhancementModuleBuildError(
            f"Не удалось прочитать {path}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise EnhancementModuleBuildError("Корень исходного JSON должен быть объектом.")
    return value


def _without_storage_keys(value: Any) -> Any:
    """Удаляет только служебные LevelDB `_key` перед сравнением документов."""
    if isinstance(value, dict):
        return {
            key: _without_storage_keys(child)
            for key, child in value.items()
            if key != "_key"
        }
    if isinstance(value, list):
        return [_without_storage_keys(child) for child in value]
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")


def _resolve_cli(explicit: str | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    environment = os.environ.get("FVTT_CLI")
    if environment:
        candidates.append(Path(environment))
    local_name = "fvtt.cmd" if os.name == "nt" else "fvtt"
    candidates.append(ROOT / "node_modules" / ".bin" / local_name)
    discovered = shutil.which("fvtt")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise EnhancementModuleBuildError(
        "Не найден официальный Foundry VTT CLI. Установите "
        "`npm install -g @foundryvtt/foundryvtt-cli` или передайте "
        "`--fvtt-cli ПУТЬ`."
    )


def _module_manifest(set_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": MODULE_ID,
        "title": str(set_data["name"]),
        "description": str(set_data["description"]),
        "version": str(set_data["version"]),
        "authors": [{"name": "Proxys"}],
        "compatibility": {
            "minimum": "13",
            "verified": project_config.FOUNDRY_VERSION,
            "maximum": "13",
        },
        "system": ["dnd5e"],
        "relationships": {
            "systems": [
                {
                    "id": "dnd5e",
                    "type": "system",
                    "compatibility": {
                        "minimum": project_config.DND5E_VERSION,
                        "verified": project_config.DND5E_VERSION,
                    },
                }
            ]
        },
        "esmodules": ["scripts/enhancement-groups.mjs"],
        "packs": [
            {
                "name": enhancement_set_builder.ENHANCERS_PACK,
                "label": "Усилители",
                "path": (
                    "packs/" + enhancement_set_builder.ENHANCERS_PACK
                ),
                "type": "Item",
                "system": "dnd5e",
                "ownership": {
                    "PLAYER": "OBSERVER",
                    "TRUSTED": "OBSERVER",
                    "ASSISTANT": "OWNER",
                },
            },
            {
                "name": enhancement_set_builder.CATALOG_PACK,
                "label": "Каталог усилений",
                "path": (
                    "packs/" + enhancement_set_builder.CATALOG_PACK
                ),
                "type": "Item",
                "system": "dnd5e",
                "ownership": {
                    "PLAYER": "OBSERVER",
                    "TRUSTED": "OBSERVER",
                    "ASSISTANT": "OWNER",
                },
            },
            {
                "name": enhancement_set_builder.TABLES_PACK,
                "label": "Таблицы усилений",
                "path": (
                    "packs/" + enhancement_set_builder.TABLES_PACK
                ),
                "type": "RollTable",
                "ownership": {
                    "PLAYER": "OBSERVER",
                    "TRUSTED": "OBSERVER",
                    "ASSISTANT": "OWNER",
                },
            },
        ],
        "packFolders": [
            {
                "name": COMPENDIUM_FOLDER,
                "sorting": "m",
                "packs": [
                    enhancement_set_builder.ENHANCERS_PACK,
                    enhancement_set_builder.CATALOG_PACK,
                    enhancement_set_builder.TABLES_PACK,
                ],
            }
        ],
    }


def _compile_pack(
    cli: Path,
    source_directory: Path,
    packs_directory: Path,
    pack_name: str,
    expected_documents: list[dict[str, Any]],
) -> None:
    expected_by_id = {
        str(document["_id"]): _without_storage_keys(document)
        for document in expected_documents
    }
    expected_document_ids = set(expected_by_id)
    cli_data_directory = packs_directory.parent.parent / ".fvtt-cli-data"
    cli_data_directory.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["XDG_DATA_HOME"] = str(cli_data_directory)
    command = [
        str(cli),
        "package",
        "pack",
        "--compendiumName",
        pack_name,
        "--inputDirectory",
        str(source_directory),
        "--outputDirectory",
        str(packs_directory),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout).strip()
        raise EnhancementModuleBuildError(
            f"Foundry VTT CLI не собрал пак {pack_name}: {details}"
        )
    destination = packs_directory / pack_name
    if not destination.is_dir() or not any(destination.iterdir()):
        raise EnhancementModuleBuildError(
            f"После сборки пак {pack_name} пуст или отсутствует."
        )
    verification_directory = packs_directory.parent.parent / "pack-verification" / pack_name
    verify_command = [
        str(cli),
        "package",
        "unpack",
        "--compendiumName",
        pack_name,
        "--inputDirectory",
        str(packs_directory),
        "--outputDirectory",
        str(verification_directory),
        "--clean",
    ]
    verified = subprocess.run(
        verify_command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if verified.returncode != 0:
        details = (verified.stderr or verified.stdout).strip()
        raise EnhancementModuleBuildError(
            f"Foundry VTT CLI не распаковал проверочный пак {pack_name}: {details}"
        )
    unpacked = list(verification_directory.rglob("*.json"))
    if len(unpacked) != len(expected_document_ids):
        raise EnhancementModuleBuildError(
            f"Пак {pack_name} содержит {len(unpacked)} документов вместо "
            f"{len(expected_document_ids)}."
        )
    unpacked_ids: set[str] = set()
    unpacked_by_id: dict[str, dict[str, Any]] = {}
    for path in unpacked:
        try:
            document = _load_json(path)
        except EnhancementModuleBuildError as error:
            raise EnhancementModuleBuildError(
                f"Обратная проверка пака {pack_name}: {error}"
            ) from error
        document_id = str(document.get("_id") or "")
        if not document_id:
            raise EnhancementModuleBuildError(
                f"Документ {path.name} в паке {pack_name} не содержит _id."
            )
        unpacked_ids.add(document_id)
        unpacked_by_id[document_id] = _without_storage_keys(document)
    if unpacked_ids != expected_document_ids:
        missing = sorted(expected_document_ids - unpacked_ids)
        extra = sorted(unpacked_ids - expected_document_ids)
        raise EnhancementModuleBuildError(
            f"Обратная проверка пака {pack_name} обнаружила расхождение ID. "
            f"Отсутствуют: {missing or 'нет'}; лишние: {extra or 'нет'}."
        )
    changed = sorted(
        document_id
        for document_id in expected_document_ids
        if unpacked_by_id[document_id] != expected_by_id[document_id]
    )
    if changed:
        raise EnhancementModuleBuildError(
            f"Обратная проверка пака {pack_name} обнаружила изменение "
            "содержимого документов после LevelDB: "
            + ", ".join(changed)
            + "."
        )


def build_archive(
    source: dict[str, Any],
    output_path: Path,
    *,
    fvtt_cli: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Проверяет набор, компилирует LevelDB-паки и создаёт ZIP."""
    documents, report = enhancement_set_builder.build_set_documents(source)
    cli = _resolve_cli(fvtt_cli)
    if not RUNTIME_SCRIPT.is_file():
        raise EnhancementModuleBuildError(
            f"Отсутствует контроллер групп: {RUNTIME_SCRIPT}"
        )

    with tempfile.TemporaryDirectory(prefix="fjb-enhancements-") as temporary:
        temporary_root = Path(temporary)
        module_root = temporary_root / MODULE_ID
        source_root = temporary_root / "pack-sources"
        packs_root = module_root / "packs"
        scripts_root = module_root / "scripts"
        packs_root.mkdir(parents=True)
        scripts_root.mkdir(parents=True)

        manifest = _module_manifest(report["set"])
        _write_json(module_root / "module.json", manifest)
        shutil.copy2(RUNTIME_SCRIPT, scripts_root / RUNTIME_SCRIPT.name)

        for pack_name, pack_documents in documents.items():
            pack_source = source_root / pack_name
            pack_source.mkdir(parents=True)
            collection = (
                "tables"
                if pack_name == enhancement_set_builder.TABLES_PACK
                else "items"
            )
            for document in pack_documents:
                packed_document = _prepare_pack_document(
                    document,
                    collection,
                )
                _write_json(
                    pack_source / f"{packed_document['_id']}.json",
                    packed_document,
                )
            _compile_pack(
                cli,
                pack_source,
                packs_root,
                pack_name,
                pack_documents,
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_archive = output_path.with_suffix(output_path.suffix + ".tmp")
        try:
            with ZipFile(
                temporary_archive, "w", compression=ZIP_DEFLATED, compresslevel=9
            ) as archive:
                for path in sorted(module_root.rglob("*")):
                    if path.is_file():
                        archive.write(
                            path,
                            (
                                Path(MODULE_ID) / path.relative_to(module_root)
                            ).as_posix(),
                        )
            with ZipFile(temporary_archive) as archive:
                broken = archive.testzip()
                if broken is not None:
                    raise EnhancementModuleBuildError(
                        f"Проверка ZIP обнаружила повреждённый файл: {broken}."
                    )
                names = archive.namelist()
                if not names or any(
                    not name.startswith(f"{MODULE_ID}/") for name in names
                ):
                    raise EnhancementModuleBuildError(
                        "ZIP содержит файл вне корневой папки модуля."
                    )
            os.replace(temporary_archive, output_path)
        finally:
            temporary_archive.unlink(missing_ok=True)

    report["output"] = project_config.portable_project_path(output_path)
    report["archive_files"] = {
        "module.json": True,
        "controller": True,
        "packs": sorted(documents),
        "packFolder": COMPENDIUM_FOLDER,
    }
    return output_path, report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Собирает enhancement_set в устанавливаемый Foundry-модуль."
    )
    parser.add_argument("source", type=Path, help="Исходный enhancement_set JSON.")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "output"
        / "enhancements"
        / f"{MODULE_ID}.zip",
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument("--fvtt-cli")
    arguments = parser.parse_args()
    try:
        source = _load_json(arguments.source)
        archive, report = build_archive(
            source,
            arguments.output,
            fvtt_cli=arguments.fvtt_cli,
        )
        report_path = arguments.report or archive.with_name(
            archive.stem + "_report.json"
        )
        _write_json(report_path, report)
    except (
        EnhancementModuleBuildError,
        enhancement_set_builder.EnhancementSetBuilderError,
    ) as error:
        print(f"Ошибка: {error}")
        return 1
    print(f"Готово: {archive}")
    print(f"Отчёт: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
