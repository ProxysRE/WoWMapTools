#!/usr/bin/env python3
"""Единая сборка класса с подклассами и/или рас из авторского JSON."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from class_builder import ClassBuilderError
from class_package_builder import build_package, write_zip
from foundry_module_builder import ModuleBuilderError, create_module, write_install_zip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output-dir', type=Path, default=Path('build'))
    parser.add_argument('--module-id', help='Собрать также устанавливаемый модуль; требует --cli-module.')
    parser.add_argument('--cli-module', type=Path, help='index.mjs официального @foundryvtt/foundryvtt-cli.')
    args = parser.parse_args()
    if bool(args.module_id) != bool(args.cli_module):
        parser.error('--module-id и --cli-module указываются вместе.')
    try:
        data = json.loads(args.input.read_text(encoding='utf-8-sig'))
        result = build_package(data, args.input.parent)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        target = args.output_dir / (result['package']['identifier'] + '.json')
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        write_zip(result, target.with_suffix('.zip'))
        print(f'Переносимый JSON: {target}')
        print(f'Архив документов: {target.with_suffix(".zip")} (не установочный модуль)')
        if args.module_id:
            module = create_module(result, args.output_dir/'modules', cli_module=args.cli_module.resolve(), module_id=args.module_id, title=result['package']['name'])
            install = args.output_dir / (args.module_id + '-module.zip')
            write_install_zip(module, install)
            print(f'Устанавливаемый модуль Foundry: {install}')
        return 0
    except (OSError, ValueError, ClassBuilderError, ModuleBuilderError) as exc:
        parser.exit(1, f'Ошибка сборки: {exc}\n')

if __name__ == '__main__':
    raise SystemExit(main())
