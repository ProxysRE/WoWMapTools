# Расходники → JSON

Правила зелий, ядов, пищи, свитков и иных расходуемых предметов. Применяй
вместе с `COMMON_JSON.md`.

## Готовая инструкция для ИИ

1. Используй секцию `templates.consumable` из `templates.json`.
2. Корневой `type` должен быть `"consumable"`. Перед сборкой оставляй
   `system.activities: {}` и помещай создаваемую механику в `mechanics`.
3. Тип находится в `system.type.value`: `potion`, `poison`, `food`, `scroll`,
   `wand`, `rod` или `trinket`.
4. Для яда укажи `system.type.subtype`: `ingested`, `contact`, `inhaled` или
   `injury`, если способ применения известен.
5. Количество применений хранится в `system.uses`. Одноразовый расходник обычно
   имеет `"max": "1"`, `"spent": 0`, `"autoDestroy": true`.
6. Допустимые activities: `attack`, `save`, `damage`, `heal`, `utility`,
   `cast`. Для `cast` обязателен `spell.uuid`.
7. Общий расход использований по умолчанию получает первая activity. Для любой
   другой activity явно ставь `consume_uses: true`, если она тоже должна
   тратить применение.
8. Постоянный эффект владельца для обычного расходника не создавай: результат
   применения должен быть связан с activity и иметь `transfer: false`.
9. Полное правило предмета, включая эффект успешного спасброска и ручные
   последствия, сохраняй в `system.description.value`.

## Одноразовый расходник

```json
{
  "name": "Зелье морозной стойкости",
  "type": "consumable",
  "system": {
    "activities": {},
    "description": {
      "value": "<p>Выпив зелье, существо получает сопротивление урону холодом на 1 час.</p>",
      "chat": ""
    },
    "type": {"value": "potion", "subtype": ""},
    "uses": {
      "max": "1",
      "spent": 0,
      "recovery": [],
      "autoDestroy": true
    }
  },
  "effects": [],
  "mechanics": {
    "activities": [
      {
        "type": "utility",
        "activity_name": "Выпить зелье",
        "activation": {"type": "action", "value": 1},
        "targeting": {
          "affects": {"count": "1", "type": "self"}
        }
      }
    ],
    "effects": [
      {
        "name": "Морозная стойкость",
        "transfer": false,
        "activity": "Выпить зелье",
        "duration": {"seconds": 3600, "rounds": null, "turns": null},
        "changes": [
          {
            "key": "system.traits.dr.value",
            "mode": "add",
            "value": "cold"
          }
        ]
      }
    ]
  }
}
```

## Яд с выбранной целью

Для эффекта на постороннюю цель activity должна явно выбирать `creature`.
Спасбросок и эффект провала связываются одной activity:

```text
"mechanics": {
  "activities": [
    {
      "type": "save",
      "activity_name": "Применить яд",
      "save": {"ability": "con", "dc": 15},
      "activation": {"type": "action", "value": 1},
      "targeting": {
        "range": {"value": 5, "units": "ft"},
        "affects": {"count": "1", "type": "creature"}
      }
    }
  ],
  "effects": [
    {
      "name": "Отравление",
      "transfer": false,
      "activity": "Применить яд",
      "on_save": false,
      "duration": {"seconds": 60, "rounds": 10, "turns": null},
      "statuses": ["poisoned"]
    }
  ]
}
```

Если автоматизация способа доставки яда не поддерживается, точное условие
применения остаётся в описании и отмечается как ручное; не заменяй его другой
механикой.
