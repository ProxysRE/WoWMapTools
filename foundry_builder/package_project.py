#!/usr/bin/env python3
"""Собирает и повторно проверяет канонический ZIP исходников проекта."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "PROJECT_MANIFEST.json"
ARCHIVE_ROOT = "Генератор JSON для импорта в FoundryVTT"
DEFAULT_OUTPUT = ROOT.parent / "FoundryVTT_Builder_Project.zip"


class ProjectPackageError(Exception):
    """Канонический архив проекта не прошёл проверку."""


def _load_manifest() -> dict:
    try:
        with MANIFEST_PATH.open("r", encoding="utf-8-sig") as file:
            manifest = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectPackageError(
            f"Не удалось прочитать PROJECT_MANIFEST.json: {error}"
        ) from error
    if not isinstance(manifest, dict):
        raise ProjectPackageError("Корень PROJECT_MANIFEST.json должен быть объектом.")
    return manifest


def _canonical_paths(manifest: dict) -> list[PurePosixPath]:
    groups = manifest.get("canonical_files")
    if not isinstance(groups, dict):
        raise ProjectPackageError("Манифест не содержит canonical_files.")
    raw_paths = [
        str(value)
        for values in groups.values()
        if isinstance(values, list)
        for value in values
    ]
    raw_paths.append("PROJECT_MANIFEST.json")
    if len(raw_paths) != len(set(raw_paths)):
        raise ProjectPackageError("Манифест содержит повторяющиеся пути.")
    result: list[PurePosixPath] = []
    for value in raw_paths:
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in value
            or value.endswith("/")
        ):
            raise ProjectPackageError(f"Небезопасный путь манифеста: {value!r}.")
        local = ROOT.joinpath(*path.parts)
        if local.is_symlink() or not local.is_file():
            raise ProjectPackageError(f"Отсутствует канонический файл: {value}.")
        try:
            local.resolve().relative_to(ROOT.resolve())
        except ValueError as error:
            raise ProjectPackageError(
                f"Путь выходит за пределы проекта: {value}."
            ) from error
        result.append(path)
    return sorted(result, key=lambda item: item.as_posix())


def _run_audit(root: Path) -> None:
    completed = subprocess.run(
        [os.environ.get("PYTHON", "python3"), "project_audit.py"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stdout + "\n" + completed.stderr).strip()
        raise ProjectPackageError(f"Аудит проекта завершился ошибкой:\n{details}")


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def _expected_names(paths: list[PurePosixPath]) -> list[str]:
    return [
        (PurePosixPath(ARCHIVE_ROOT) / path).as_posix()
        for path in paths
    ]


def build_archive(output: Path) -> Path:
    manifest = _load_manifest()
    paths = _canonical_paths(manifest)
    _run_audit(ROOT)
    expected_names = _expected_names(paths)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    temporary_output = output.with_suffix(output.suffix + ".tmp")
    try:
        with ZipFile(
            temporary_output,
            "w",
            compression=ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path, archive_name in zip(paths, expected_names, strict=True):
                archive.writestr(
                    _zip_info(archive_name),
                    ROOT.joinpath(*path.parts).read_bytes(),
                )

        with ZipFile(temporary_output) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ProjectPackageError("ZIP содержит повторяющиеся записи.")
            if names != expected_names:
                missing = sorted(set(expected_names) - set(names))
                extra = sorted(set(names) - set(expected_names))
                raise ProjectPackageError(
                    f"Состав ZIP не совпал с манифестом. "
                    f"Отсутствуют: {missing or 'нет'}; лишние: {extra or 'нет'}."
                )
            broken = archive.testzip()
            if broken is not None:
                raise ProjectPackageError(f"ZIP повреждён: {broken}.")
            for path, archive_name in zip(paths, names, strict=True):
                if archive.read(archive_name) != ROOT.joinpath(*path.parts).read_bytes():
                    raise ProjectPackageError(
                        f"Содержимое {archive_name} изменилось при упаковке."
                    )

        with tempfile.TemporaryDirectory(prefix="foundry-builder-project-") as tmp:
            temporary_root = Path(tmp)
            with ZipFile(temporary_output) as archive:
                for name in archive.namelist():
                    path = PurePosixPath(name)
                    if path.is_absolute() or ".." in path.parts:
                        raise ProjectPackageError(
                            f"ZIP содержит небезопасный путь: {name}."
                        )
                archive.extractall(temporary_root)
            extracted_root = temporary_root / ARCHIVE_ROOT
            extracted_files = sorted(
                path.relative_to(extracted_root).as_posix()
                for path in extracted_root.rglob("*")
                if path.is_file()
            )
            expected_files = sorted(path.as_posix() for path in paths)
            if extracted_files != expected_files:
                raise ProjectPackageError(
                    "Повторно распакованный ZIP содержит неверный набор файлов."
                )
            for path in paths:
                source = ROOT.joinpath(*path.parts)
                extracted = extracted_root.joinpath(*path.parts)
                if source.read_bytes() != extracted.read_bytes():
                    raise ProjectPackageError(
                        f"Повторная проверка обнаружила изменение {path}."
                    )
            _run_audit(extracted_root)

        os.replace(temporary_output, output)
    finally:
        temporary_output.unlink(missing_ok=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Собирает проверенный FoundryVTT_Builder_Project.zip."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    try:
        archive = build_archive(arguments.output)
    except ProjectPackageError as error:
        print(f"Сборка проекта остановлена: {error}")
        return 1
    print(f"Канонический архив создан: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
