#!/usr/bin/env python3
"""Единый источник целевых версий и переносимых путей проекта."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "PROJECT_MANIFEST.json"


class ProjectConfigError(RuntimeError):
    """PROJECT_MANIFEST.json отсутствует или содержит неверную конфигурацию."""


def _load_manifest() -> dict[str, Any]:
    try:
        with MANIFEST_PATH.open("r", encoding="utf-8-sig") as file:
            manifest = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectConfigError(
            f"Не удалось прочитать {MANIFEST_PATH.name}: {error}"
        ) from error
    if not isinstance(manifest, dict):
        raise ProjectConfigError("Корень PROJECT_MANIFEST.json должен быть объектом.")
    targets = manifest.get("targets")
    if not isinstance(targets, dict):
        raise ProjectConfigError("PROJECT_MANIFEST.json не содержит объект targets.")
    required = (
        "foundry",
        "export_core",
        "dnd5e",
        "midi-qol",
        "dae",
        "enhancements_module",
    )
    missing = [key for key in required if not str(targets.get(key) or "").strip()]
    if missing:
        raise ProjectConfigError(
            "В PROJECT_MANIFEST.json отсутствуют целевые версии: "
            + ", ".join(missing)
        )
    return manifest


MANIFEST = _load_manifest()
TARGETS = MANIFEST["targets"]
FOUNDRY_VERSION = str(TARGETS["foundry"])
EXPORT_CORE_VERSION = str(TARGETS["export_core"])
DND5E_VERSION = str(TARGETS["dnd5e"])
MIDI_QOL_VERSION = str(TARGETS["midi-qol"])
DAE_VERSION = str(TARGETS["dae"])
ENHANCEMENTS_MODULE_VERSION = str(TARGETS["enhancements_module"])


def normalize_export_versions(value: Any) -> None:
    """Rewrites Foundry schema stamps to the oldest supported V13 build.

    A document exported by a newer patch is rejected by an older Foundry
    patch before the system can migrate it.  The builder emits the V13 schema
    used by 13.347, so every nested Document receives that compatibility stamp.
    D&D5e's systemVersion remains exact because it controls system migrations.
    """
    if isinstance(value, dict):
        stats = value.get("_stats")
        if isinstance(stats, dict):
            stats["coreVersion"] = EXPORT_CORE_VERSION
        for child in value.values():
            normalize_export_versions(child)
    elif isinstance(value, list):
        for child in value:
            normalize_export_versions(child)


def portable_project_path(path: Path) -> str:
    """Возвращает POSIX-путь относительно проекта, если файл находится в нём."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)
