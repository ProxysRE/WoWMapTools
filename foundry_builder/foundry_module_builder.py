#!/usr/bin/env python3
"""Сборка переносимого пакета класса в устанавливаемый модуль Foundry VTT."""

from __future__ import annotations

import argparse
import os
import json
import shutil
import subprocess
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any
import re
from class_builder import ClassBuilderError, IDENTIFIER
from package_validation import validate_documents


DEFAULT_MODULE_ID = "foundry-custom-content"
DEFAULT_MODULE_TITLE = "Авторский контент"
DEFAULT_VERSION = "0.4.0"
DEFAULT_FOUNDRY_VERSION = "13"
DEFAULT_DND5E_MINIMUM = "5.3.0"
DEFAULT_DND5E_VERIFIED = "5.3.3"


class ModuleBuilderError(ValueError):
    """Ошибка входных данных или сборки модуля."""


def prepare_documents(
    package: dict[str, Any],
    *,
    module_id: str = DEFAULT_MODULE_ID,
    class_pack: str = "classes",
    feature_pack: str = "features",
    race_pack: str = "races",
) -> dict[str, list[dict[str, Any]]]:
    """Сохраняет внешние UUID; переносит только ссылки собственного пакета."""
    if not IDENTIFIER.fullmatch(module_id):
        raise ModuleBuilderError("module_id: нужны строчные a-z, цифры и дефисы.")
    names = [class_pack, feature_pack, race_pack]
    if len(set(names + ["spells", "backgrounds", "feats", "equipment"])) != 7 or any(not IDENTIFIER.fullmatch(n) for n in names):
        raise ModuleBuilderError("Имена компендиумов должны быть допустимыми и уникальными.")
    try:
        source_id = package["package"]["identifier"]
        if not IDENTIFIER.fullmatch(source_id):
            raise ClassBuilderError("Некорректный identifier пакета.")
        groups = validate_documents(package["documents"], source_id)
    except (KeyError, TypeError, ClassBuilderError) as exc:
        raise ModuleBuilderError(str(exc)) from exc
    rename = {"classes": class_pack, "features": feature_pack, "races": race_pack, "spells": "spells", "backgrounds": "backgrounds", "feats": "feats", "equipment": "equipment"}
    mapping = {
        f"Compendium.{source_id}.{pack}.Item.{item['_id']}": f"Compendium.{module_id}.{rename[pack]}.Item.{item['_id']}"
        for pack, items in groups.items() for item in items
    }
    pattern = re.compile(r"Compendium\." + re.escape(source_id) + r"\.[A-Za-z0-9_-]+\.Item\.[A-Za-z0-9]+")
    def replace(value):
        if isinstance(value, dict):
            return {k: replace(v) for k, v in value.items()}
        if isinstance(value, list):
            return [replace(v) for v in value]
        if isinstance(value, str):
            return pattern.sub(lambda m: mapping[m.group()], value)
        return value
    return {rename[pack]: replace(items) for pack, items in groups.items() if items}


def _walk_strings(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, str):
        yield value


def build_manifest(
    *,
    module_id: str = DEFAULT_MODULE_ID,
    title: str = DEFAULT_MODULE_TITLE,
    version: str = DEFAULT_VERSION,
    class_pack: str = "classes",
    feature_pack: str = "features",
    race_pack: str = "races",
) -> dict[str, Any]:
    return {
        "id": module_id,
        "title": title,
        "description": "Авторские классы, подклассы, расы и особенности для D&D 5e.",
        "version": version,
        "authors": [{"name": "Proxys"}],
        "compatibility": {
            "minimum": DEFAULT_FOUNDRY_VERSION,
            "verified": DEFAULT_FOUNDRY_VERSION,
            "maximum": DEFAULT_FOUNDRY_VERSION,
        },
        "system": ["dnd5e"],
        "esmodules": ["scripts/resource-pools.mjs"],
        "relationships": {
            "systems": [
                {
                    "id": "dnd5e",
                    "type": "system",
                    "compatibility": {
                        "minimum": DEFAULT_DND5E_MINIMUM,
                        "verified": DEFAULT_DND5E_VERIFIED,
                    },
                }
            ]
        },
        "packs": [
            {
                "name": "spells", "label": "Заклинания", "system": "dnd5e",
                "path": "packs/spells", "type": "Item",
                "ownership": {"PLAYER": "OBSERVER", "TRUSTED": "OBSERVER", "ASSISTANT": "OWNER"},
            },
            {
                "name": class_pack,
                "label": "Авторские классы и подклассы",
                "system": "dnd5e",
                "path": f"packs/{class_pack}",
                "type": "Item",
                "ownership": {
                    "PLAYER": "OBSERVER",
                    "TRUSTED": "OBSERVER",
                    "ASSISTANT": "OWNER",
                },
            },
            {
                "name": race_pack,
                "label": "Авторские расы и подрасы",
                "system": "dnd5e",
                "path": f"packs/{race_pack}",
                "type": "Item",
                "ownership": {"PLAYER": "OBSERVER", "TRUSTED": "OBSERVER", "ASSISTANT": "OWNER"},
            },
            {
                "name": feature_pack,
                "label": "Авторские особенности",
                "system": "dnd5e",
                "path": f"packs/{feature_pack}",
                "type": "Item",
                "ownership": {
                    "PLAYER": "OBSERVER",
                    "TRUSTED": "OBSERVER",
                    "ASSISTANT": "OWNER",
                },
            },
        ],
        "packFolders": [
            {
                "name": "Авторский контент Proxys",
                "sorting": "m",
                "packs": [class_pack, race_pack, feature_pack, "spells"],
            }
        ],
        "readme": "README.md",
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _source_filename(index: int, document: dict[str, Any]) -> str:
    document_id = document["_id"]
    return f"{index:03d}-{document['type']}-{document_id}.json"


def _add_compendium_keys(document: dict[str, Any]) -> None:
    """Добавляет ключи Foundry CLI корневому Item и вложенным Effects."""
    document_id = str(document["_id"])
    document["_key"] = f"!items!{document_id}"
    effects = document.get("effects", [])
    if not isinstance(effects, list):
        return
    for effect in effects:
        if not isinstance(effect, dict) or not effect.get("_id"):
            continue
        effect["_key"] = (
            f"!items.effects!{document_id}.{effect['_id']}"
        )


def _write_readme(path: Path, module_id: str) -> None:
    path.write_text(
        f"""# Авторский контент Proxys

Модуль авторских классов для Foundry VTT 13 и D&D 5e 5.3.x.

Содержит:

- классы и подклассы из собранного пакета;
- кастомные расы и законченные варианты подрас;
- связанные с ними особенности;
- компендиумы классов, рас и особенностей со стабильными UUID;
- общий механизм классовых ресурсов с восстановлением после отдыха.

## Установка

1. Закройте Foundry VTT.
2. Распакуйте архив в каталог пользовательских данных `Data/modules`.
3. Убедитесь, что итоговый путь выглядит как
   `Data/modules/{module_id}/module.json`.
4. Запустите Foundry и откройте нужный мир D&D 5e.
5. В меню «Управление модулями» включите «Авторский контент Proxys».

## Использование

1. Откройте вкладку «Компендиумы».
2. Откройте «Авторские классы и подклассы».
3. Перетащите нужный класс на лист персонажа.
4. Выберите подкласс на предусмотренном классом уровне.

Расы перетащите из компендиума рас на лист персонажа. Подраса уже содержит
общие и собственные черты: базовую расу вместе с ней не добавляйте.

Особенности из компендиума особенностей вручную импортировать не нужно. Развитие
класса копирует их на персонажа по UUID.
""",
        encoding="utf-8",
    )


def _compile_pack(
    source: Path,
    destination: Path,
    *,
    cli_module: Path,
) -> None:
    source_js = """
const { compilePack } = await import(process.argv[1]);
await compilePack(process.argv[2], process.argv[3], { log: true });
"""
    completed = subprocess.run(
        [
            "node",
            "--input-type=module",
            "--eval",
            source_js,
            cli_module.resolve().as_uri(),
            str(source),
            str(destination),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise ModuleBuilderError(
            "Официальный Foundry CLI не смог собрать компендиум.\n"
            + completed.stdout
            + completed.stderr
        )


def _create_module_staged(
    package: dict[str, Any],
    output_root: Path,
    *,
    cli_module: Path,
    module_id: str = DEFAULT_MODULE_ID,
    title: str = DEFAULT_MODULE_TITLE,
    version: str = DEFAULT_VERSION,
) -> Path:
    """Создаёт модуль с присутствующими в пакете LevelDB-компендиумами."""

    class_pack = "classes"
    feature_pack = "features"
    prepared = prepare_documents(
        package,
        module_id=module_id,
        class_pack=class_pack,
        feature_pack=feature_pack,
    )
    module_root = output_root / module_id
    module_root.mkdir(parents=True)
    manifest = build_manifest(module_id=module_id, title=title, version=version,
                              class_pack=class_pack, feature_pack=feature_pack)
    for name, label in (("backgrounds", "Предыстории"), ("feats", "Черты"), ("equipment", "Снаряжение")):
        if name in prepared:
            manifest["packs"].append({"name":name,"label":label,"system":"dnd5e","path":"packs/"+name,"type":"Item","ownership":{"PLAYER":"OBSERVER","TRUSTED":"OBSERVER","ASSISTANT":"OWNER"}})
    manifest["packs"] = [p for p in manifest["packs"] if p["name"] in prepared]
    manifest["packFolders"][0]["packs"] = list(prepared)
    _write_json(module_root / "module.json", manifest)
    _write_readme(module_root / "README.md", module_id)
    runtime_source = Path(__file__).resolve().parent / "runtime" / "resource-pools.mjs"
    if not runtime_source.exists():
        raise ModuleBuilderError(
            "Не найден runtime/resource-pools.mjs для классовых ресурсов."
        )
    runtime_target = module_root / "scripts" / "resource-pools.mjs"
    runtime_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(runtime_source, runtime_target)

    with tempfile.TemporaryDirectory(prefix="foundry-module-source-") as temp:
        source_root = Path(temp)
        from compendium_layout import organize, ownership_paths
        ownership = ownership_paths(prepared)
        for pack_name, documents in prepared.items():
            documents, folders = organize(documents, pack_name, ownership=ownership, link_lists=package.get("native_spell_lists", False))
            pack_source = source_root / pack_name
            pack_source.mkdir(parents=True)
            for index, document in enumerate(documents, start=1):
                source_document = deepcopy(document)
                _add_compendium_keys(source_document)
                _write_json(
                    pack_source / _source_filename(index, document),
                    source_document,
                )
            for folder in folders:
                _write_json(pack_source / ("folder-" + folder["_id"] + ".json"), folder)
            _compile_pack(
                pack_source,
                module_root / "packs" / pack_name,
                cli_module=cli_module,
            )
    return module_root


def create_module(package: dict[str, Any], output_root: Path, *, cli_module: Path,
                  module_id: str = DEFAULT_MODULE_ID, title: str = DEFAULT_MODULE_TITLE,
                  version: str = DEFAULT_VERSION) -> Path:
    """Компилирует во временном каталоге, публикует только готовый модуль."""
    prepare_documents(package, module_id=module_id)
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".module-build-", dir=output_root) as temp:
        stage = Path(temp)
        built = _create_module_staged(package, stage, cli_module=cli_module,
                                     module_id=module_id, title=title, version=version)
        target, backup = output_root / module_id, stage / "previous"
        if target.exists():
            target.rename(backup)
        try:
            built.rename(target)
        except Exception:
            if backup.exists():
                backup.rename(target)
            raise
    return target


def write_install_zip(module_root: Path, target: Path) -> None:
    """Записывает ZIP с верхнеуровневой папкой модуля для ручной установки."""

    files = sorted(path for path in module_root.rglob("*") if path.is_file())
    expected = [(Path(module_root.name) / path.relative_to(module_root)).as_posix() for path in files]
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name+".", suffix=".partial", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                for path, name in zip(files, expected):
                    archive.write(path, name)
            temporary.flush()
            os.fsync(temporary.fileno())
        with zipfile.ZipFile(temporary_path) as archive:
            if archive.namelist() != expected or archive.testzip() is not None:
                raise ModuleBuilderError("Проверка установочного ZIP не пройдена")
        temporary_path.replace(target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("build"))
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--module-id", default=DEFAULT_MODULE_ID)
    parser.add_argument("--title", default=DEFAULT_MODULE_TITLE)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument(
        "--cli-module",
        required=True,
        type=Path,
        help="Путь к index.mjs официального @foundryvtt/foundryvtt-cli.",
    )
    args = parser.parse_args()
    package = json.loads(args.package.read_text(encoding="utf-8-sig"))
    module_root = create_module(
        package,
        args.output_root,
        cli_module=args.cli_module,
        module_id=args.module_id,
        title=args.title,
        version=args.version,
    )
    target = args.zip or args.output_root / f"{args.module_id}.zip"
    write_install_zip(module_root, target)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
