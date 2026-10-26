# Оружие и оружейные атаки → JSON

Профиль оружия и врождённых атак NPC. Общие правила activities, формул,
ресурсов, эффектов и ручной механики находятся в `COMMON_JSON.md`. Для оружия
внутри NPC также применяй `NPC_JSON.md`.

## 1. Обязательный контракт

1. Бери структуру из `templates.weapon` в `templates.json`; корневой `type`
   равен `"weapon"`.
2. До сборки оставляй `system.activities: {}`. Рабочую механику помещай в
   корневой `mechanics`.
3. Полностью сохраняй правило, разумность, личность, конфликт, восстановление
   зарядов и способ уничтожения в `system.description.value`.
4. Базовый урон настоящего оружия записывай в `system.damage`. Обычный бонус
   `+1/+2/+3` к атаке и урону — только в `system.magicalBonus`; не дублируй
   его в формуле урона или `attack.bonus`.
5. Для атаки владельца используй `"bonus": ""`, `"flat": false`. Для атаки
   NPC с указанным итогом — `"ability": "none"`, полный `bonus` и
   `"flat": true`; фиксированный модификатор урона оставляй в формуле.
6. Обычная attack-activity настоящего оружия использует базовый урон. Не ставь
   ей `include_base: false`; дополнительные типы урона перечисляй отдельными
   частями.
7. Одна отдельно нажимаемая часть — одна activity. Условный урон, поздний
   урон, временные хиты и последующий спасбросок отделяй от основной атаки и
   задавай им точное условие через `activation.type: "special"`.
8. Общие заряды хранятся в `system.uses` либо `mechanics.uses`. Только первая
   кнопка способности расходует их через `itemUses`; вспомогательные кнопки
   повторно ресурс не списывают. Собственные использования activity задавай
   её полем `uses` — билдер создаст `activityUses`.
9. Для состояния или изменения параметра используй общий
   `mechanics.effects` и привяжи эффект к нужной activity. Неподдерживаемые
   последствия сохраняй точным текстом.
10. В `chatFlavor` сложной activity укажи её цель, условие, стоимость и ручные
    последствия. Механика в JSON не заменяет понятного описания способности.
11. Для отдельного оружия и носимого оружия NPC всегда заполняй
    `enhancement_policy` по `ITEM_ENHANCEMENT_POLICY.md`.
12. Перед ответом сверь все заголовки, формулы, Сл, расходы и длительности с
    исходником. Ничего не оставляй только в кратком названии activity.

## 2. Поля оружия

Минимально значимая часть `system`:

```json
{
  "activities": {},
  "description": {"value": "<p>Полное правило предмета.</p>", "chat": ""},
  "uses": {"max": "5", "spent": 0, "recovery": []},
  "damage": {
    "base": {
      "number": 1,
      "denomination": 8,
      "bonus": "",
      "types": ["slashing"],
      "custom": {"enabled": false, "formula": ""},
      "scaling": {"mode": "", "number": null, "formula": ""}
    },
    "versatile": {
      "number": 1,
      "denomination": 10,
      "bonus": "",
      "types": ["slashing"],
      "custom": {"enabled": false, "formula": ""},
      "scaling": {"mode": "", "number": null, "formula": ""}
    }
  },
  "magicalBonus": 2,
  "type": {"value": "martialM", "baseItem": "longsword"},
  "properties": ["mgc", "ver"],
  "rarity": "veryRare",
  "attunement": "required",
  "attuned": false,
  "equipped": true
}
```

Не создавай вымышленные системные поля для характера разумного предмета,
случайных свойств или способа уничтожения.

## 3. Атаки и составные способности

Одна фиксированная атака NPC:

```json
{
  "mechanics": {
    "attack": {
      "ability": "none",
      "bonus": "+11",
      "flat": true,
      "type": "melee",
      "classification": "weapon"
    },
    "damage": [
      {"formula": "2d8+6", "type": "slashing"},
      {"formula": "3d6", "type": "necrotic"}
    ],
    "range": {
      "reach": 5,
      "units": "ft",
      "count": 1,
      "target_type": "creature"
    },
    "activation": {"type": "action", "value": 1}
  }
}
```

Для дальней атаки вместо `reach` используй `value` и при наличии `long`.
`attack.type`: `melee` или `ranged`; `classification`: `weapon` либо `spell`.

Составная способность использует `mechanics.activities` с типами `attack`,
`save`, `damage`, `heal`, `utility`. Например, атака и спасбросок после
попадания — две activities; вторая имеет пустой `damage` и условие
`"После попадания основной атакой"`.

Отдельный условный урон:

```json
{
  "type": "damage",
  "activity_name": "Дополнительный урон нежити",
  "damage": [{"formula": "2d10", "type": "radiant"}],
  "activation": {
    "type": "special",
    "value": null,
    "condition": "После попадания по нежити"
  }
}
```

Расход общих зарядов добавляй только активирующей кнопке:

```json
{
  "consumption": [
    {
      "type": "itemUses",
      "target": "",
      "value": "2",
      "scaling": {"mode": "", "formula": ""}
    }
  ]
}
```

Критический порог допустим в `attack.critical.threshold`. Бонусный критический
урон без отдельного типа можно записать в `attack.critical.bonus`; если у него
собственный тип урона, создай условную `damage`-activity.

Шаблон области находится в `range.template`:

```json
{
  "range": {
    "value": 120,
    "units": "ft",
    "count": "",
    "target_type": "creatureOrObject",
    "template": {"type": "sphere", "size": 20, "units": "ft"}
  }
}
```

## 4. Совместимость с усилениями

Заполни только политику самого оружия по `ITEM_ENHANCEMENT_POLICY.md`. Не открывай
`ENHANCEMENTS_JSON.md`, если пользователь прямо не просит создать усилитель,
усиление, набор, пул или таблицу.
