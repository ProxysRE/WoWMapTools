# Экипировка → JSON

Правила доспехов, щитов, колец, одежды, жезлов и иных носимых предметов.
Применяй вместе с `COMMON_JSON.md`.

## Готовая инструкция для ИИ

1. Используй секцию `templates.equipment` из `templates.json`.
2. Корневой `type` должен быть `"equipment"`. Перед сборкой оставляй
   `system.activities: {}` и помещай создаваемую механику в `mechanics`.
3. Для брони заполни `system.type.value`, `system.type.baseItem`,
   `system.armor.value`, `system.armor.dex` и при необходимости
   `system.armor.magicalBonus`.
4. Бонус `+1/+2/+3` доспеха или щита записывай только в
   `system.armor.magicalBonus`; не создавай для него Active Effect на КД.
5. Требование настройки указывай как `system.attunement: "required"`.
6. Общие заряды находятся в `system.uses` либо `mechanics.uses`. При нескольких
   кнопках заряд по умолчанию расходует только первая; используй
   `consume_uses`, если конкретная activity тоже должна тратить заряд.
7. Допустимые activities: `attack`, `save`, `damage`, `heal`, `utility`,
   `cast`. Для `cast` обязателен `spell.uuid`.
8. Постоянный эффект владельца создавай с `transfer: true`. Эффект выбранной
   цели создавай с `transfer: false` и привязывай к activity.
9. Полное описание предмета сохраняй даже при полной автоматизации.
10. Всегда заполняй корневой `enhancement_policy` по
    `ITEM_ENHANCEMENT_POLICY.md`. Не открывай `ENHANCEMENTS_JSON.md`, если
    пользователь прямо не просит создать усилитель, усиление, набор,
    пул или таблицу.

## Поля брони

```json
{
  "name": "Латный доспех +2",
  "type": "equipment",
  "system": {
    "activities": {},
    "description": {
      "value": "<p>Очень редкий доспех.</p>",
      "chat": ""
    },
    "type": {"value": "heavy", "baseItem": "plate"},
    "armor": {"value": 18, "dex": 0, "magicalBonus": "2"},
    "properties": ["mgc", "stealthDisadvantage", "gear"],
    "strength": 15,
    "rarity": "veryRare",
    "attunement": "",
    "attuned": false,
    "equipped": true,
    "uses": {"max": "", "spent": 0, "recovery": []}
  },
  "effects": []
}
```

`system.type.value`:

- `light`, `medium`, `heavy` — классы доспехов;
- `shield` — щит;
- `clothing`, `ring`, `trinket`, `wand`, `rod`, `staff` — прочая экипировка.

Для средней брони `armor.dex` обычно равен `2`, для тяжёлой — `0`, для лёгкой
и щита — `null`. У щита `armor.value` содержит его прибавку к КД, обычно `2`.

## Постоянный эффект владельца

```text
"mechanics": {
  "passive": true,
  "effects": [
    {
      "name": "Сопротивление холоду",
      "transfer": true,
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
```

## Заряды и активная способность

```text
"mechanics": {
  "uses": {
    "max": 3,
    "spent": 0,
    "recovery": [
      {"period": "dawn", "type": "formula", "formula": "1d3"}
    ]
  },
  "activities": [
    {
      "type": "save",
      "activity_name": "Приказ доспеха",
      "save": {"ability": "wis", "dc": 15},
      "damage": [],
      "activation": {"type": "action", "value": 1},
      "targeting": {
        "range": {"value": 30, "units": "ft"},
        "affects": {"count": "1", "type": "creature"}
      }
    }
  ]
}
```

## Наложение заклинания

```json
{
  "type": "cast",
  "activity_name": "Телепортация",
  "spell": {
    "uuid": "Compendium.dnd5e.spells.Item.L4J89JXqbKs6puEV",
    "level": 7,
    "challenge": {
      "attack": null,
      "save": null,
      "override": false
    },
    "properties": ["vocal", "somatic", "material"]
  },
  "activation": {"type": "action", "value": 1}
}
```

Для нескольких способностей используй `mechanics.activities`. У каждой
activity явно ставь `consume_uses: true`, только если она отдельно расходует
общий заряд предмета.
