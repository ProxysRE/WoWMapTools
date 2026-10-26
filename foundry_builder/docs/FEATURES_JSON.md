# Особенности и действия → JSON

Правила черт, действий, бонусных действий, реакций, легендарных действий и
составных способностей. Применяй вместе с `COMMON_JSON.md`.

## Готовая инструкция для ИИ: самостоятельная особенность

Если пользователь просит преобразовать отдельную черту, действие, бонусное
действие, реакцию или легендарное действие:

1. Верни один JSON-объект по структуре `templates.feat` из `templates.json`.
2. Корневой `type` должен быть `"feat"`. Перед сборкой оставляй
   `system.activities: {}` и `effects: []`.
3. Полный исходный текст сохраняй в `system.description.value`, а временную
   разметку — в корневом `mechanics`.
4. Допустимые activities: `attack`, `save`, `damage`, `heal`, `utility`.
5. Для постоянной пассивной особенности без кнопки используй
   `"passive": true`. Если системного эффекта тоже нет, `mechanics` можно
   полностью не добавлять. Если пассивное свойство должно иметь вспомогательную
   кнопку урона, лечения или броска, не ставь `passive: true`: создай
   соответствующую activity с `activation.type: "special"` и запиши условие
   срабатывания в `activation.condition`.
6. Составную особенность разбивай на отдельные элементы
   `mechanics.activities`. Общий расход использований по умолчанию получает
   только первая кнопка. Для другого порядка явно ставь
   `"consume_uses": true` у расходующей кнопки и `false` у вспомогательных.
   У простой особенности с одной activity и непустым `mechanics.uses` одно
   использование расходуется автоматически; `consume_uses: false` ставь
   только если эта кнопка действительно бесплатна.
7. Для состояния или изменения системного поля используй
   `mechanics.effects`. Эффект цели создавай с `transfer: false` и привязывай
   к activity; постоянный эффект владельца — с `transfer: true`.
8. Легендарное действие задавай через
   `activation: {"type": "legendary", "value": <стоимость>}`. Билдер сам
   расходует такое же количество `resources.legact.value`.
9. Легендарная стойкость с activation `special` автоматически расходует
   `resources.legres.value`.
10. Не превращай условное уменьшение урона в нанесение урона. Для броска
    величины снижения используй `utility.roll`.

## 8. Простая активная особенность

Спасбросок и урон:

```text
"mechanics": {
  "activity_name": "Название броска",
  "save": {"ability": "wis", "dc": 20},
  "damage": [
    {"formula": "4d10", "type": "necrotic"}
  ],
  "on_save": "half",
  "activation": {"type": "action", "value": 1},
  "range": {"value": 60, "units": "ft"},
  "target": {
    "affects": {
      "count": 3,
      "type": "creature",
      "choice": true
    }
  }
}
```

`on_save`:

- `half` — половина урона при успехе;
- `none` — нет урона при успехе либо способность не наносит урон.

Область от самого существа:

```text
"range": {"units": "self"},
"target": {
  "template": {
    "type": "radius",
    "size": 30,
    "units": "ft"
  },
  "affects": {
    "type": "creature",
    "choice": false
  },
  "prompt": true
}
```

Допустимые формы области: `cone`, `line`, `radius`, `sphere`, `cube`, `cylinder`.

`choice` управляет не формой области, а способом выбора целей:

- `choice: false` — все подходящие существа внутри шаблона; используй для
  автоматических конусов, линий, сфер, радиусов, кубов и цилиндров;
- `choice: true` — мастер вручную выбирает одну или несколько целей; используй
  для точечных и выборочных эффектов, но не для обычного взрыва или ауры;
- `prompt: true` — Foundry предлагает разместить или направить шаблон.

Не заполняй `affects.special` текстом вроде «все существа в области», если
обычных полей `template` и `affects` достаточно. Непустое `special` переводит
цель в особый ручной режим и может помешать автоматическому выделению Midi-QOL.

Лечение:

```text
"mechanics": {
  "healing": {"formula": "1d10+5", "type": "healing"},
  "activation": {"type": "bonus", "value": 1},
  "range": {"units": "self"},
  "target": {"affects": {"type": "self"}}
}
```

Для временных хитов используй `"type": "temphp"`.

Урон без броска атаки и без спасброска:

```text
"mechanics": {
  "activity_type": "damage",
  "activation": {"type": "bonus", "value": 1},
  "damage": [
    {"formula": "2d6", "type": "necrotic"}
  ],
  "range": {"value": 10, "units": "ft"},
  "target": {
    "affects": {
      "count": 1,
      "type": "creature",
      "choice": true
    }
  }
}
```

`utility.roll` используй только для броска, который не является уроном, лечением, атакой или спасброском.

## 9. Составная особенность

Допустимые типы активности особенности: `attack`, `save`, `damage`, `heal`,
`utility`.

Атака особенностью использует ту же структуру `attack`, что и оружие:

```json
{
  "type": "attack",
  "activity_name": "Легендарный коготь",
  "activation": {"type": "legendary", "value": 1},
  "attack": {
    "ability": "none",
    "bonus": "+12",
    "flat": true,
    "type": "melee",
    "classification": "weapon"
  },
  "damage": [
    {"formula": "2d10+6", "type": "slashing"},
    {"formula": "2d8", "type": "psychic"}
  ],
  "targeting": {
    "range": {"value": 10, "units": "ft"},
    "affects": {"count": 1, "type": "creature"}
  }
}
```

Важное отличие: внутри `mechanics.activities` особенности цели записываются в `targeting`, а не в `range` и `target`.

```text
"mechanics": {
  "activities": [
    {
      "type": "save",
      "activity_name": "Спасбросок цели",
      "activation": {
        "type": "reaction",
        "value": 1,
        "condition": "Существо в пределах 60 фт. восстанавливает хиты"
      },
      "save": {"ability": "cha", "dc": 20},
      "damage": [],
      "targeting": {
        "range": {"value": 60, "units": "ft"},
        "affects": {"count": 1, "type": "creature"}
      }
    },
    {
      "type": "heal",
      "activity_name": "Лечение НПС",
      "activation": {
        "type": "special",
        "value": null,
        "condition": "После провала спасброска цели"
      },
      "healing": {"formula": "15", "type": "healing"},
      "targeting": {
        "range": {"units": "self"},
        "affects": {"type": "self"}
      }
    }
  ]
}
```

Если у составной особенности есть `mechanics.uses`, только первая activity
расходует одно использование автоматически. Чтобы заряд расходовала другая
кнопка, поставь первой `"consume_uses": false`, а нужной —
`"consume_uses": true`. Явный массив `consumption` всегда имеет приоритет.

Ошибочный тип activity, некорректный или повторяющийся `_id`, непривязанный
эффект и отсутствие обязательных полей теперь попадают в отчёт билдера, а не
исчезают молча.
