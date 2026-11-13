from typing import Any

def _control_package() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "strict_automation": True,
        "identifier": "audit-package",
        "name": "Контрольный пакет",
        "class": {
            "name": "Контрольный класс",
            "identifier": "audit-class",
            "description": "<p>Служебный пример аудита.</p>",
            "hit_die": "d8",
            "primary_abilities": ["wis"],
            "spellcasting": {"progression": "none", "ability": ""},
            "advancement": [
                {"type": "hit_points"},
                {
                    "type": "item_grant",
                    "level": 1,
                    "title": "Контрольная особенность",
                    "items": [
                        {"ref": "feature:audit-action", "optional": False}
                    ],
                },
                {"type": "subclass", "level": 3},
            ],
        },
        "subclass": {
            "name": "Контрольный подкласс",
            "identifier": "audit-path",
            "class_identifier": "audit-class",
            "description": "<p>Служебный пример аудита.</p>",
            "spellcasting": {"progression": "none", "ability": ""},
            "advancement": [],
        },
        "features": [
            {
                "key": "feature:audit-action",
                "name": "Контрольное действие",
                "description": "<p>Создаёт нажимаемую activity.</p>",
                "automation": {"mode": "full"},
                "mechanics": {
                    "activity_type": "utility",
                    "activity_name": "Проверить",
                    "activation": {"type": "action", "value": 1},
                },
            }
        ],
    }
