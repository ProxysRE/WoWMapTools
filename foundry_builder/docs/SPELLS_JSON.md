# Заклинания → JSON

Профиль самостоятельных заклинаний и заклинаний NPC. Общие правила activities,
формул, эффектов, ресурсов и ручной механики находятся в `COMMON_JSON.md`. Для
заклинания внутри NPC также применяй `NPC_JSON.md`.

## 1. Обязательный контракт

1. Бери структуру из `templates.spell` в `templates.json`; корневой `type`
   равен `"spell"`.
2. До сборки оставляй `system.activities: {}` и `effects: []`. Рабочую
   механику помещай в корневой `mechanics`.
3. В `system.description.value` сохраняй полный эффект и раздел «На высших
   кругах». Не дублируй название, круг, школу, время накладывания, дистанцию,
   компоненты и длительность: они находятся в отдельных полях.
4. Заполняй круг, школу, компоненты, материальную стоимость и расход,
   активацию, дистанцию, длительность, цель или область и концентрацию.
5. Уровневое заклинание расходует ячейку; заговор — нет. Не отключай расход
   без прямого правила.
6. Масштабирование добавляй только тогда, когда оно явно дано в исходном
   тексте.
7. Составное заклинание разделяй на `mechanics.activities`; состояния и
   изменения параметров помещай в общий `mechanics.effects` с привязкой к
   нужной activity.
8. Для области продублируй форму в `mechanics.targeting.template`: обязательны
   `type`, `size`, `units`. Используй `prompt: true`,
   `affects.choice: false` и по умолчанию
   `auto_target_action: "alwaysIgnoreDefeated"`.
9. Перед ответом сверь все формулы, Сл, цели, длительности, компоненты и
   масштабирование с исходником.

## 2. Системные поля заклинания

Минимальный профиль:

```json
{
  "name": "Огненный шар",
  "type": "spell",
  "system": {
    "description": {
      "value": "<p>Полный текст эффекта без повторения системных сведений.</p>",
      "chat": ""
    },
    "activation": {"type": "action", "value": 1, "condition": ""},
    "duration": {"value": "", "units": "inst"},
    "target": {
      "affects": {
        "type": "creature",
        "count": "",
        "choice": false,
        "special": ""
      },
      "template": {
        "type": "sphere",
        "size": 20,
        "units": "ft",
        "contiguous": false,
        "stationary": false
      }
    },
    "range": {"value": 150, "units": "ft", "special": ""},
    "uses": {"max": "", "spent": 0, "recovery": []},
    "level": 3,
    "school": "evo",
    "materials": {
      "value": "Крошечный шарик из гуано летучей мыши и серы",
      "consumed": false,
      "cost": 0,
      "supply": 0
    },
    "properties": ["vocal", "somatic", "material"],
    "activities": {},
    "identifier": "",
    "method": "spell",
    "prepared": 1
  },
  "effects": []
}
```

Коды школ: `abj` — ограждение, `con` — вызов, `div` — прорицание, `enc` —
очарование, `evo` — воплощение, `ill` — иллюзия, `nec` — некромантия,
`trs` — преобразование.

Свойства: `vocal`, `somatic`, `material`, `concentration`, `ritual`.
`level` равен `0` для заговора и `1–9` для уровневого заклинания.
Материальный компонент полностью записывай в `materials.value`; его расход и
стоимость не выводи из художественного описания приблизительно.

## 3. NPC-заклинатель

У актёра укажи характеристику, уровень заклинателя и текущие ячейки:

```json
{
  "attributes": {
    "spellcasting": "int",
    "spell": {"level": 18}
  },
  "spells": {
    "spell0": {"value": 0, "override": null},
    "spell1": {"value": 4, "override": null},
    "spell2": {"value": 3, "override": null},
    "spell3": {"value": 3, "override": null},
    "spell4": {"value": 0, "override": null},
    "spell5": {"value": 0, "override": null},
    "spell6": {"value": 0, "override": null},
    "spell7": {"value": 0, "override": null},
    "spell8": {"value": 0, "override": null},
    "spell9": {"value": 0, "override": null},
    "pact": {"value": 0, "override": null}
  }
}
```

`attributes.spell.level` — именно уровень заклинателя, не CR и не максимальный
круг. Без него ячейки могут отображаться только как временные. Для нового
актёра также сохрани полный корневой `_stats` из `templates.npc`: отсутствие
`systemVersion` может привести к устаревшей миграции и сбросу уровня.

Не придумывай отсутствующие ячейки. Для обычного NPC используй
`override: null`; `value` соответствует текущему запасу свежего заклинателя,
если статблок не говорит иное.

## 4. Activities

Допустимы `attack`, `save`, `damage`, `heal`, `utility`.

Атака заклинанием владельца:

```json
{
  "mechanics": {
    "activity_type": "attack",
    "attack": {
      "ability": "",
      "bonus": "",
      "flat": false,
      "type": "ranged"
    },
    "damage": [{"formula": "1d10", "type": "fire"}]
  }
}
```

Пустые `ability` и `bonus` используют показатель атаки заклинанием владельца.
Для фиксированного бонуса NPC укажи `"ability": "none"`, полный `bonus` и
`"flat": true`.

Спасбросок с уроном:

```json
{
  "mechanics": {
    "activity_type": "save",
    "save": {"ability": "dex", "dc": "spellcasting"},
    "damage": [{"formula": "8d6", "type": "fire"}],
    "on_save": "half"
  }
}
```

`dc: "spellcasting"` использует Сл владельца; отдельную фиксированную Сл пиши
числом. Урон без атаки и спасброска использует `damage`; лечение — `heal` с
`healing.formula` и `healing.type`.

В составном заклинании ячейку по умолчанию расходует только первая activity.
Вспомогательные кнопки не расходуют её повторно. Исключение размечай явным
`"spell_slot": true` или `"spell_slot": false`.

## 5. Области и Midi-QOL

Для `cone`, `cube`, `cylinder`, `line`, `radius`, `sphere` и `wall` задай
одинаковую геометрию в системной цели и в `mechanics.targeting.template`.
Билдер по умолчанию применяет:

```json
{
  "auto_target_action": "alwaysIgnoreDefeated",
  "midi_properties": {"confirmTargets": "always"}
}
```

Это выбирает живые токены под размещённым шаблоном и просит подтвердить список.
Если стены блокируют область, используй
`"auto_target_action": "wallsBlockIgnoreDefeated"`. Значение `"default"`
наследует настройку мира; `midi_properties.confirmTargets: "never"` отключает
подтверждение для конкретной activity.

## 6. Масштабирование

В `formula` всегда записывай базовый урон или лечение. `scaling` помещай только
в ту часть, которая действительно увеличивается.

Одинаковая дополнительная кость за каждый шаг:

```json
{
  "formula": "8d6",
  "type": "fire",
  "scaling": {"mode": "whole", "number": 1}
}
```

Иная прибавка:

```json
{
  "formula": "3d4+3",
  "type": "force",
  "scaling": {"mode": "whole", "formula": "1d4+1"}
}
```

`whole` применяет прибавку на каждом шаге, `half` — за каждые два шага,
пустой режим отключает масштабирование. Для заговора формула отражает урон на
1-м уровне существа; Foundry применяет следующие шаги по уровню. Для уровневого
заклинания шагом является уровень ячейки выше `system.level`.

## 7. Эффекты

Используй контракт `mechanics.effects` из `COMMON_JSON.md`. При нескольких
activities обязательно укажи `activity` по индексу, точному `activity_name`
или `_id`; для нескольких — массив, для всех — `"all"`. Длительность эффекта
по умолчанию наследуется из `system.duration`.

Полный текст заклинания сохраняй даже при наличии автоматизированного эффекта.
