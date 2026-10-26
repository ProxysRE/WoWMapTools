#!/usr/bin/env python3
"""Графическое приложение для JSON-билдеров Foundry VTT.

Приложение не зависит от папки ``input`` и не запускает билдеры через
командную строку. Исходный JSON можно открыть с диска, вставить в редактор
или получить из одного из канонических шаблонов проекта.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import actor_builder
import build_enhancement_module
import build_npc
import consumable_builder
import enhancement_builder
import enhancement_set_builder
import equipment_builder
import feat_builder
import item_builder
import midi_compat
import project_config
import spell_builder
import weapon_builder


ROOT = Path(__file__).resolve().parent
APP_TITLE = "Foundry JSON Builder"
APP_VERSION = "1.5"

WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class AppBuildError(Exception):
    """Ошибка, которую можно безопасно показать пользователю приложения."""


@dataclass(frozen=True)
class BuilderSpec:
    key: str
    label: str
    description: str
    template_key: str
    standalone_kind: str


@dataclass
class BuildOutcome:
    builder_key: str
    document: dict[str, Any]
    report: dict[str, Any]
    kind: str
    compatibility: dict[str, Any]


BUILDERS = (
    BuilderSpec(
        "npc",
        "Полный лист НПС",
        "Полная рекомендуемая цепочка: актёр, особенности, оружие, "
        "экипировка, заклинания, расходники и обычные предметы.",
        "npc",
        "actor",
    ),
    BuilderSpec(
        "feat",
        "Особенность",
        "Черта, действие, реакция, бонусное или легендарное действие.",
        "feat",
        "feat",
    ),
    BuilderSpec(
        "weapon",
        "Оружие",
        "Обычное, магическое или артефактное оружие.",
        "weapon",
        "weapon",
    ),
    BuilderSpec(
        "equipment",
        "Экипировка",
        "Доспех, щит, кольцо, одежда, жезл или иной носимый предмет.",
        "equipment",
        "equipment",
    ),
    BuilderSpec(
        "spell",
        "Заклинание",
        "Самостоятельное заклинание с activities и Active Effects.",
        "spell",
        "spell",
    ),
    BuilderSpec(
        "consumable",
        "Расходник",
        "Зелье, яд, пища, свиток или другой расходуемый предмет.",
        "consumable",
        "consumable",
    ),
    BuilderSpec(
        "item",
        "Обычный предмет",
        "Добыча, сокровище, материал, снаряжение или хлам без механики.",
        "item",
        "loot",
    ),
    BuilderSpec(
        "enhancement",
        "Усиление",
        "Проверка одного профиля Enchantment и создание записи каталога.",
        "enhancement",
        "enhancement",
    ),
    BuilderSpec(
        "enhancement_set",
        "Набор усилений",
        "Проверка набора, создание усилителей, таблиц, паков и ZIP-модуля.",
        "enhancement_set",
        "enhancement_set",
    ),
)

SPECS_BY_KEY = {spec.key: spec for spec in BUILDERS}
KEY_BY_LABEL = {spec.label: spec.key for spec in BUILDERS}
TYPE_TO_BUILDER = {
    "npc": "npc",
    "feat": "feat",
    "weapon": "weapon",
    "equipment": "equipment",
    "spell": "spell",
    "consumable": "consumable",
    "loot": "item",
    "enhancement": "enhancement",
    "enhancement_set": "enhancement_set",
}
KIND_FOLDERS = {
    "actor": "actors",
    "feat": "items",
    "weapon": "weapons",
    "equipment": "equipment",
    "spell": "spells",
    "consumable": "consumables",
    "loot": "items",
    "enhancement": "enhancements",
    "enhancement_set": "enhancements",
}


def parse_json_text(text: str, source_name: str = "редактор") -> dict[str, Any]:
    if not text.strip():
        raise AppBuildError("Редактор пуст. Откройте файл, вставьте JSON или загрузите шаблон.")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise AppBuildError(
            f"Ошибка JSON в «{source_name}»: строка {error.lineno}, "
            f"столбец {error.colno}: {error.msg}"
        ) from error
    if not isinstance(value, dict):
        raise AppBuildError("Корень JSON должен быть объектом, заключённым в { }.")
    return value


def load_json_file(path: Path) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise AppBuildError(f"Не удалось прочитать файл:\n{path}\n\n{error}") from error
    return parse_json_text(text, path.name), text


def detect_builder(source: dict[str, Any]) -> str | None:
    document_type = str(source.get("type") or "").casefold()
    if document_type in TYPE_TO_BUILDER:
        return TYPE_TO_BUILDER[document_type]
    if isinstance(source.get("items"), list) and isinstance(source.get("system"), dict):
        return "npc"
    return None


def _report_to_dict(report: Any) -> dict[str, Any]:
    if isinstance(report, dict):
        return report
    if is_dataclass(report):
        value = asdict(report)
        if isinstance(value, dict):
            return value
    raise AppBuildError("Билдер вернул отчёт неизвестного формата.")


def _audit_or_raise(document: dict[str, Any]) -> dict[str, Any]:
    compatibility = midi_compat.audit_document(document)
    errors = compatibility.get("errors")
    if isinstance(errors, list) and errors:
        details = "; ".join(str(error) for error in errors[:5])
        if len(errors) > 5:
            details += f"; и ещё {len(errors) - 5} ошибок"
        raise AppBuildError(
            "Итоговый JSON не прошёл проверку Midi-QOL/DAE: " + details
        )
    return compatibility


def build_document(
    builder_key: str,
    source: dict[str, Any],
    source_name: str = "встроенный редактор",
) -> BuildOutcome:
    """Запускает выбранный билдер без чтения или замены файлов в ``input``."""
    if builder_key not in SPECS_BY_KEY:
        raise AppBuildError(f"Неизвестный билдер: {builder_key}")
    detected = detect_builder(source)
    if detected and detected != builder_key:
        raise AppBuildError(
            f"Этот JSON относится к режиму «{SPECS_BY_KEY[detected].label}», "
            f"а выбран режим «{SPECS_BY_KEY[builder_key].label}». "
            "Выберите подходящий билдер."
        )

    source_contract = (
        {"activities": 0, "errors": [], "warnings": []}
        if builder_key in {"enhancement", "enhancement_set"}
        else midi_compat.audit_source_document(source)
    )
    if source_contract["errors"]:
        details = "; ".join(source_contract["errors"][:5])
        if len(source_contract["errors"]) > 5:
            details += (
                f"; и ещё {len(source_contract['errors']) - 5} ошибок"
            )
        raise AppBuildError(
            "Исходный JSON не прошёл смысловую проверку: " + details
        )

    try:
        if builder_key == "npc":
            document, report = build_npc.build_npc(
                source,
                source_name=source_name,
            )
            kind = "actor"
            report_dict = report
        elif builder_key == "enhancement":
            validated = enhancement_builder.validate_document(source)
            enhancement = validated["enhancement"]
            rider_activities, rider_effects = (
                enhancement_builder.build_rider_documents(
                    enhancement,
                    set_id="standalone_enhancement",
                    schema_version=validated["schema_version"],
                )
            )
            document = enhancement_builder.build_catalog_item(
                enhancement,
                set_id="standalone_enhancement",
                schema_version=validated["schema_version"],
            )
            report_dict = {
                "schema_version": validated["schema_version"],
                "enhancement": {
                    "id": enhancement["id"],
                    "name": enhancement["name"],
                    "group": enhancement["group"],
                    "tier": enhancement["tier"],
                    "rider_activities": len(rider_activities),
                    "rider_effects": len(rider_effects),
                },
                "warnings": [
                    "Создана запись каталога. Для рабочего усилителя включите "
                    "профиль в enhancement_set."
                ],
            }
            kind = "enhancement"
        elif builder_key == "enhancement_set":
            validated = enhancement_set_builder.validate_set(source)
            documents, report_dict = (
                enhancement_set_builder.build_set_documents(validated)
            )
            errors: list[str] = []
            activities = 0
            effects = 0
            for pack_name in (
                enhancement_set_builder.ENHANCERS_PACK,
                enhancement_set_builder.CATALOG_PACK,
            ):
                for document_index, item in enumerate(documents[pack_name]):
                    result = midi_compat.audit_document(item)
                    activities += int(result.get("activities") or 0)
                    effects += int(result.get("effects") or 0)
                    errors.extend(
                        f"{pack_name}[{document_index}]: {message}"
                        for message in result["errors"]
                    )
            if errors:
                raise AppBuildError(
                    "Документы набора усилений не прошли итоговую проверку: "
                    + "; ".join(errors[:5])
                )
            document = validated
            kind = "enhancement_set"
            compatibility = {
                "target": {
                    "dnd5e": project_config.DND5E_VERSION,
                    "midi-qol": project_config.MIDI_QOL_VERSION,
                    "dae": project_config.DAE_VERSION,
                },
                "activities": activities,
                "effects": effects,
                "errors": [],
                "warnings": [],
            }
        else:
            normalizers: dict[str, Callable[..., tuple[Any, Any, str]]] = {
                "feat": feat_builder.normalize_document,
                "weapon": weapon_builder.normalize_document,
                "equipment": equipment_builder.normalize_document,
                "spell": spell_builder.normalize_document,
                "consumable": consumable_builder.normalize_document,
                "item": item_builder.normalize_document,
            }
            document, report, kind = normalizers[builder_key](
                source,
                source_name=source_name,
            )
            report_dict = _report_to_dict(report)
    except (
        actor_builder.ActorBuilderError,
        build_npc.NpcBuildError,
        consumable_builder.ConsumableBuilderError,
        equipment_builder.EquipmentBuilderError,
        feat_builder.FeatBuilderError,
        item_builder.ItemBuilderError,
        spell_builder.SpellBuilderError,
        weapon_builder.WeaponBuilderError,
        enhancement_builder.EnhancementBuilderError,
        enhancement_set_builder.EnhancementSetBuilderError,
        build_enhancement_module.EnhancementModuleBuildError,
    ) as error:
        raise AppBuildError(str(error)) from error
    except (KeyError, TypeError, ValueError) as error:
        raise AppBuildError(f"Билдер не смог обработать исходные данные: {error}") from error

    if not isinstance(document, dict):
        raise AppBuildError("Билдер вернул некорректный итоговый документ.")

    if builder_key != "enhancement_set":
        project_config.normalize_export_versions(document)
        compatibility = _audit_or_raise(document)
    report_dict["source_contract"] = source_contract
    report_dict["midi_compatibility"] = compatibility
    report_dict["application"] = {
        "name": APP_TITLE,
        "version": APP_VERSION,
        "builder": builder_key,
    }
    return BuildOutcome(
        builder_key=builder_key,
        document=document,
        report=report_dict,
        kind=kind,
        compatibility=compatibility,
    )


def _safe_filename(value: str) -> str:
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    filename = re.sub(r"\s+", " ", filename)
    if not filename:
        filename = "Безымянный"
    if filename.upper() in WINDOWS_RESERVED_FILENAMES:
        filename = f"_{filename}"
    return filename


def default_output_directory(kind: str) -> Path:
    return ROOT / "output" / KIND_FOLDERS.get(kind, "items")


def suggested_output_path(outcome: BuildOutcome, directory: Path) -> Path:
    if outcome.kind == "enhancement_set":
        return directory / f"{enhancement_builder.MODULE_ID}.zip"
    name = _safe_filename(str(outcome.document.get("name") or "Безымянный"))
    return directory / f"{name}_foundry.json"


def _atomic_json_write(path: Path, value: Any, indent: int = 2) -> None:
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
            json.dump(value, temporary, ensure_ascii=False, indent=indent)
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
        raise AppBuildError(f"Не удалось сохранить файл:\n{path}\n\n{error}") from error


def save_outcome(
    outcome: BuildOutcome,
    output_directory: Path | None = None,
) -> tuple[Path, Path]:
    directory = output_directory or default_output_directory(outcome.kind)
    output_path = suggested_output_path(outcome, directory)
    if outcome.kind == "enhancement_set":
        try:
            output_path, module_report = build_enhancement_module.build_archive(
                outcome.document,
                output_path,
            )
        except (
            build_enhancement_module.EnhancementModuleBuildError,
            enhancement_set_builder.EnhancementSetBuilderError,
        ) as error:
            raise AppBuildError(str(error)) from error
        outcome.report.update(module_report)
        report_path = output_path.with_name(output_path.stem + "_report.json")
        _atomic_json_write(report_path, outcome.report)
        return output_path, report_path

    report_path = ROOT / "logs" / "app" / f"{output_path.stem}_report.json"
    outcome.report["output"] = project_config.portable_project_path(output_path)
    _atomic_json_write(output_path, outcome.document)
    _atomic_json_write(report_path, outcome.report)
    return output_path, report_path


def _collect_warnings(value: Any) -> list[str]:
    warnings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "warnings" and isinstance(child, list):
                warnings.extend(str(item) for item in child)
            else:
                warnings.extend(_collect_warnings(child))
    elif isinstance(value, list):
        for child in value:
            warnings.extend(_collect_warnings(child))
    return list(dict.fromkeys(warnings))


def outcome_summary(outcome: BuildOutcome, output_path: Path, report_path: Path) -> str:
    activities = int(outcome.compatibility.get("activities") or 0)
    effects = int(outcome.compatibility.get("effects") or 0)
    warnings = _collect_warnings(outcome.report)
    lines = [
        f"Готово: {outcome.document.get('name') or 'Безымянный'}",
        f"Файл: {output_path}",
        f"Отчёт: {report_path}",
        f"Activities: {activities}; Active Effects: {effects}.",
    ]
    if warnings:
        lines.append(f"Предупреждений: {len(warnings)}")
        lines.extend(f"• {warning}" for warning in warnings[:8])
        if len(warnings) > 8:
            lines.append(f"• И ещё {len(warnings) - 8}.")
    else:
        lines.append("Ошибок и предупреждений нет.")
    return "\n".join(lines)


def self_test_errors() -> list[str]:
    """Проверяет работу приложения со всеми каноническими шаблонами."""
    errors: list[str] = []
    for spec in BUILDERS:
        try:
            source = equipment_builder.load_template(spec.template_key)
            source_name = f"templates.json:{spec.template_key}"
            once = build_document(spec.key, source, source_name=source_name)
            repeat_source = source if spec.key == "enhancement" else once.document
            twice = build_document(
                spec.key,
                repeat_source,
                source_name=f"{source_name}: повторный прогон",
            )
            if once.document != twice.document:
                errors.append(
                    f"{spec.label}: повторная сборка изменяет итоговый JSON."
                )
        except Exception as error:
            errors.append(f"{spec.label}: {error}")
    return errors


def _open_in_system(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as error:
        raise AppBuildError(f"Не удалось открыть:\n{path}\n\n{error}") from error


class BuilderApplication:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.source_path: Path | None = None
        self.last_output: Path | None = None
        self.last_report: Path | None = None
        self.output_directory_custom = False
        self.building = False
        self.build_queue: queue.Queue[tuple[str, Any]] = queue.Queue()

        self.builder_var = tk.StringVar(value=BUILDERS[0].label)
        self.source_var = tk.StringVar(value="Новый документ")
        self.output_var = tk.StringVar(
            value=str(default_output_directory(BUILDERS[0].standalone_kind))
        )
        self.description_var = tk.StringVar(value=BUILDERS[0].description)
        self.status_var = tk.StringVar(value="Готов к работе")

        self._configure_window()
        self._build_interface()
        self.load_template()

    def _configure_window(self) -> None:
        self.root.title(f"{APP_TITLE} {APP_VERSION}")
        self.root.geometry("1120x800")
        self.root.minsize(860, 640)
        self.root.option_add("*tearOff", False)

        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10))
        style.configure("Build.TButton", font=("Segoe UI", 11, "bold"), padding=(18, 10))
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 10, "bold"))

    def _build_interface(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        container = ttk.Frame(self.root, padding=14)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text=(
                f"JSON → готовый импорт Foundry VTT "
                f"{project_config.FOUNDRY_VERSION} / D&D5e "
                f"{project_config.DND5E_VERSION} / "
                "Midi-QOL / DAE"
            ),
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        setup = ttk.LabelFrame(
            container,
            text=" 1. Выберите сборку ",
            style="Section.TLabelframe",
            padding=10,
        )
        setup.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        setup.columnconfigure(1, weight=1)
        ttk.Label(setup, text="Билдер:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.builder_box = ttk.Combobox(
            setup,
            textvariable=self.builder_var,
            values=[spec.label for spec in BUILDERS],
            state="readonly",
            width=28,
        )
        self.builder_box.grid(row=0, column=1, sticky="w")
        self.builder_box.bind("<<ComboboxSelected>>", self._on_builder_changed)
        ttk.Label(
            setup,
            textvariable=self.description_var,
            wraplength=680,
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        source = ttk.LabelFrame(
            container,
            text=" 2. Откройте, вставьте или отредактируйте JSON ",
            style="Section.TLabelframe",
            padding=10,
        )
        source.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        source.columnconfigure(0, weight=1)
        ttk.Label(source, textvariable=self.source_var).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        buttons = ttk.Frame(source)
        buttons.grid(row=0, column=1, sticky="e", pady=(0, 8))
        ttk.Button(buttons, text="Открыть JSON…", command=self.open_source).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(buttons, text="Вставить JSON", command=self.paste_source).grid(
            row=0, column=1, padx=(0, 6)
        )
        ttk.Button(buttons, text="Загрузить шаблон", command=self.load_template).grid(
            row=0, column=2, padx=(0, 6)
        )
        ttk.Button(buttons, text="Сохранить исходник…", command=self.save_source).grid(
            row=0, column=3
        )

        editor_frame = ttk.Frame(container)
        editor_frame.grid(row=3, column=0, sticky="nsew")
        editor_frame.columnconfigure(0, weight=1)
        editor_frame.rowconfigure(0, weight=1)
        self.editor = ScrolledText(
            editor_frame,
            wrap="none",
            undo=True,
            font=("Consolas", 10),
            padx=8,
            pady=8,
        )
        self.editor.grid(row=0, column=0, sticky="nsew")
        self.editor.bind("<Control-Return>", lambda _event: self.start_build())
        self.editor.bind("<Control-s>", lambda _event: self.save_source())

        output = ttk.LabelFrame(
            container,
            text=" 3. Соберите готовый JSON ",
            style="Section.TLabelframe",
            padding=10,
        )
        output.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        output.columnconfigure(1, weight=1)
        ttk.Label(output, text="Папка результата:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Entry(output, textvariable=self.output_var).grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(output, text="Выбрать…", command=self.choose_output_directory).grid(
            row=0, column=2, padx=(8, 0)
        )
        ttk.Button(output, text="Проверить JSON", command=self.validate_source).grid(
            row=1, column=0, sticky="w", pady=(10, 0)
        )
        self.build_button = ttk.Button(
            output,
            text="СОБРАТЬ ДЛЯ FOUNDRY",
            command=self.start_build,
            style="Build.TButton",
        )
        self.build_button.grid(row=1, column=1, sticky="e", pady=(10, 0))
        result_buttons = ttk.Frame(output)
        result_buttons.grid(row=1, column=2, sticky="e", pady=(10, 0), padx=(8, 0))
        self.open_file_button = ttk.Button(
            result_buttons,
            text="Открыть файл",
            command=self.open_last_output,
            state="disabled",
        )
        self.open_file_button.grid(row=0, column=0, padx=(0, 6))
        self.open_folder_button = ttk.Button(
            result_buttons,
            text="Открыть папку",
            command=self.open_last_output_directory,
            state="disabled",
        )
        self.open_folder_button.grid(row=0, column=1)

        log_frame = ttk.LabelFrame(container, text=" Результат ", padding=8)
        log_frame.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        log_frame.columnconfigure(0, weight=1)
        self.log = ScrolledText(
            log_frame,
            height=6,
            wrap="word",
            state="disabled",
            font=("Segoe UI", 9),
        )
        self.log.grid(row=0, column=0, sticky="ew")

        ttk.Label(
            container,
            textvariable=self.status_var,
            anchor="w",
            relief="sunken",
            padding=(6, 3),
        ).grid(row=6, column=0, sticky="ew", pady=(8, 0))

    def _selected_key(self) -> str:
        return KEY_BY_LABEL.get(self.builder_var.get(), "npc")

    def _set_editor_text(self, text: str) -> None:
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self.editor.edit_reset()

    def _write_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", text)
        self.log.configure(state="disabled")

    def _set_default_output_for_key(self, key: str) -> None:
        if self.output_directory_custom:
            return
        spec = SPECS_BY_KEY[key]
        self.output_var.set(str(default_output_directory(spec.standalone_kind)))

    def _on_builder_changed(self, _event: object | None = None) -> None:
        key = self._selected_key()
        self.description_var.set(SPECS_BY_KEY[key].description)
        self._set_default_output_for_key(key)
        self.status_var.set(f"Выбран билдер: {SPECS_BY_KEY[key].label}")

    def _inspect_and_detect(
        self,
        show_success: bool = False,
        autodetect: bool = True,
    ) -> dict[str, Any] | None:
        try:
            document = parse_json_text(
                self.editor.get("1.0", "end-1c"),
                self.source_var.get(),
            )
        except AppBuildError as error:
            messagebox.showerror("Некорректный JSON", str(error), parent=self.root)
            self.status_var.set("В JSON найдена ошибка")
            return None

        detected = detect_builder(document)
        if detected and autodetect:
            self.builder_var.set(SPECS_BY_KEY[detected].label)
            self.description_var.set(SPECS_BY_KEY[detected].description)
            self._set_default_output_for_key(detected)
        if show_success:
            name = document.get("name") or "Безымянный"
            builder = SPECS_BY_KEY[detected].label if detected else "не определён"
            messagebox.showinfo(
                "JSON корректен",
                f"Документ: {name}\nПодходящий билдер: {builder}",
                parent=self.root,
            )
        return document

    def open_source(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self.root,
            title="Открыть исходный JSON",
            filetypes=(("JSON", "*.json"), ("Все файлы", "*.*")),
        )
        if not filename:
            return
        path = Path(filename)
        try:
            _document, text = load_json_file(path)
        except AppBuildError as error:
            messagebox.showerror("Не удалось открыть файл", str(error), parent=self.root)
            return
        self.source_path = path
        self.source_var.set(str(path))
        self._set_editor_text(text)
        self._inspect_and_detect()
        self.status_var.set(f"Открыт файл: {path.name}")
        self._write_log("Файл загружен. При необходимости отредактируйте JSON и нажмите «СОБРАТЬ ДЛЯ FOUNDRY».")

    def paste_source(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showwarning(
                "Буфер обмена пуст",
                "В буфере обмена нет текста.",
                parent=self.root,
            )
            return
        self.source_path = None
        self.source_var.set("JSON из буфера обмена")
        self._set_editor_text(text)
        self._inspect_and_detect()
        self.status_var.set("JSON вставлен из буфера обмена")

    def load_template(self) -> None:
        spec = SPECS_BY_KEY[self._selected_key()]
        try:
            document = equipment_builder.load_template(spec.template_key)
            text = json.dumps(document, ensure_ascii=False, indent=2)
        except equipment_builder.EquipmentBuilderError as error:
            messagebox.showerror("Не удалось открыть шаблон", str(error), parent=self.root)
            return
        self.source_path = None
        self.source_var.set(
            f"Шаблон: templates.json → {spec.template_key}"
        )
        self._set_editor_text(text)
        self.status_var.set(f"Загружен шаблон: {spec.label}")
        self._write_log(
            "Шаблон загружен в редактор. Изменения не затронут основной файл шаблона."
        )

    def save_source(self) -> str | None:
        initial_name = self.source_path.name if self.source_path else "source.json"
        filename = filedialog.asksaveasfilename(
            parent=self.root,
            title="Сохранить исходный JSON",
            defaultextension=".json",
            initialfile=initial_name,
            filetypes=(("JSON", "*.json"),),
        )
        if not filename:
            return None
        path = Path(filename)
        document = self._inspect_and_detect(autodetect=False)
        if document is None:
            return None
        try:
            _atomic_json_write(path, document)
        except AppBuildError as error:
            messagebox.showerror("Не удалось сохранить", str(error), parent=self.root)
            return None
        self.source_path = path
        self.source_var.set(str(path))
        self.status_var.set(f"Исходник сохранён: {path.name}")
        return "break"

    def choose_output_directory(self) -> None:
        directory = filedialog.askdirectory(
            parent=self.root,
            title="Выберите папку для готовых JSON",
            initialdir=self.output_var.get() or str(ROOT),
        )
        if directory:
            self.output_directory_custom = True
            self.output_var.set(directory)
            self.status_var.set("Папка результата изменена")

    def validate_source(self) -> None:
        document = self._inspect_and_detect()
        if document is None:
            return
        builder_key = self._selected_key()
        try:
            outcome = build_document(
                builder_key,
                document,
                source_name=self.source_var.get(),
            )
        except AppBuildError as error:
            messagebox.showerror(
                "Проверка не пройдена",
                str(error),
                parent=self.root,
            )
            self.status_var.set("JSON не прошёл полную проверку")
            self._write_log("ОШИБКА ПРОВЕРКИ:\n" + str(error))
            return
        warnings = _collect_warnings(outcome.report)
        summary = (
            f"Режим: {SPECS_BY_KEY[builder_key].label}\n"
            "Синтаксис, исходная схема и итоговая структура проверены.\n"
            f"Activities: {outcome.compatibility.get('activities', 0)}; "
            f"Active Effects: {outcome.compatibility.get('effects', 0)}."
        )
        if warnings:
            summary += f"\nПредупреждений: {len(warnings)}."
        messagebox.showinfo(
            "Полная проверка пройдена",
            summary,
            parent=self.root,
        )
        self.status_var.set("JSON прошёл полную проверку")
        self._write_log(summary)

    def start_build(self) -> None:
        if self.building:
            return
        source = self._inspect_and_detect(autodetect=False)
        if source is None:
            return
        builder_key = self._selected_key()
        output_directory_text = self.output_var.get().strip()
        if not output_directory_text:
            messagebox.showerror(
                "Не выбрана папка",
                "Укажите папку для готового JSON.",
                parent=self.root,
            )
            return
        output_directory = Path(output_directory_text)
        if not self.output_directory_custom and detect_builder(source) == "npc":
            output_directory = default_output_directory("actor")
            self.output_var.set(str(output_directory))
        source_name = str(self.source_path) if self.source_path else self.source_var.get()

        self.building = True
        self.build_button.configure(state="disabled", text="СБОРКА…")
        self.status_var.set("Идёт сборка и проверка…")
        self._write_log(
            f"Запущено: {SPECS_BY_KEY[builder_key].label}\n"
            "Пожалуйста, дождитесь завершения."
        )

        def worker() -> None:
            try:
                outcome = build_document(builder_key, source, source_name=source_name)
                output_path, report_path = save_outcome(outcome, output_directory)
                summary = outcome_summary(outcome, output_path, report_path)
            except Exception as error:
                self.build_queue.put(("error", error))
                return
            self.build_queue.put(
                (
                    "success",
                    (outcome, output_path, report_path, summary),
                )
            )

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll_build_queue)

    def _poll_build_queue(self) -> None:
        try:
            status, payload = self.build_queue.get_nowait()
        except queue.Empty:
            if self.building:
                self.root.after(100, self._poll_build_queue)
            return
        if status == "error":
            self._build_failed(payload)
            return
        outcome, output_path, report_path, summary = payload
        self._build_succeeded(
            outcome,
            output_path,
            report_path,
            summary,
        )

    def _finish_build_state(self) -> None:
        self.building = False
        self.build_button.configure(state="normal", text="СОБРАТЬ ДЛЯ FOUNDRY")

    def _build_failed(self, error: Exception) -> None:
        self._finish_build_state()
        text = str(error) if str(error) else error.__class__.__name__
        self.status_var.set("Сборка завершилась ошибкой")
        self._write_log("ОШИБКА:\n" + text)
        messagebox.showerror("Сборка не выполнена", text, parent=self.root)

    def _build_succeeded(
        self,
        _outcome: BuildOutcome,
        output_path: Path,
        report_path: Path,
        summary: str,
    ) -> None:
        self._finish_build_state()
        self.last_output = output_path
        self.last_report = report_path
        self.open_file_button.configure(state="normal")
        self.open_folder_button.configure(state="normal")
        self.status_var.set(f"Готово: {output_path.name}")
        self._write_log(summary)
        messagebox.showinfo(
            "Сборка завершена",
            f"Готовый JSON создан:\n{output_path}",
            parent=self.root,
        )

    def open_last_output(self) -> None:
        if not self.last_output:
            return
        try:
            _open_in_system(self.last_output)
        except AppBuildError as error:
            messagebox.showerror("Не удалось открыть файл", str(error), parent=self.root)

    def open_last_output_directory(self) -> None:
        if not self.last_output:
            return
        try:
            _open_in_system(self.last_output.parent)
        except AppBuildError as error:
            messagebox.showerror("Не удалось открыть папку", str(error), parent=self.root)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Графическое приложение JSON-билдеров.")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Проверить все билдеры без открытия окна.",
    )
    parser.add_argument("--version", action="version", version=APP_VERSION)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.self_test:
        errors = self_test_errors()
        if errors:
            print("Самопроверка приложения не пройдена:")
            for error in errors:
                print(f"- {error}")
            return 1
        print(
            f"{APP_TITLE} {APP_VERSION}: все {len(BUILDERS)} режимов работают."
        )
        return 0

    try:
        root = tk.Tk()
    except tk.TclError as error:
        print(f"Не удалось открыть графическое окно: {error}", file=sys.stderr)
        return 1
    BuilderApplication(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
