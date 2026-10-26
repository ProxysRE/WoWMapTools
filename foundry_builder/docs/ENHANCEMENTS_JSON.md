# Усиления → первичный JSON

Версия схемы: 7

Используй этот документ только для устанавливаемых усилений и их наборов.
Если механику нужно придумать, сначала открой `docs/CONTENT_DESIGN.md`.
Полную структуру всегда бери из `templates.enhancement` или
`templates.enhancement_set` в `templates.json`.

ИИ создаёт первичный контракт, а не готовый Foundry Item. Не добавляй `_id`,
UUID, сырые `flags`, `system.activities`, готовые Enchantment-эффекты, макросы
или JavaScript.

## 1. Корневые форматы

Одно усиление:

```json
{
  "schema_version": 7,
  "type": "enhancement",
  "enhancement": {}
}
```

Набор усилений, расходников и таблиц:

```json
{
  "schema_version": 7,
  "type": "enhancement_set",
  "set": {},
  "groups": [],
  "enhancements": [],
  "bundles": [],
  "pools": []
}
```

Для набора `groups`, `enhancements` и `pools` непустые; `bundles` может быть
пустым. Каждое усиление определяется один раз в `enhancements`, а таблицы
ссылаются на него по ID.

Все машинные ID стабильны, уникальны в своей области и соответствуют
`[a-z][a-z0-9_]{2,63}`. Русские названия находятся в `name`.

## 2. Граница системы

Устанавливаемое усиление — Enchantment одной канонической группы.

`material_property` не является усилением. Оно задаётся только в
`enhancement_policy.material_property` готового оружия или экипировки, не
занимает обычные группы либо `signature_property` и не устанавливается
расходником.

Встроенные свойства готового предмета перечисляются в
`enhancement_policy.native_properties`. Политика `locked` запрещает внешние
усиления; старый артефакт без явной политики также считается закрытым.

## 3. Канонические группы

Новые ID групп создавать нельзя. В наборе объявляй используемые группы с
`rule: "replace_any"`.

| Группа | Единственное самостоятельное свойство |
|---|---|
| `numeric_bonus` | постоянный `+1/+2/+3` |
| `additional_damage` | дополнительные кости урона |
| `offensive_property` | крит, состояние при попадании, пробитие |
| `defensive_property` | сопротивление, снижение урона, защита |
| `attribute_property` | характеристика, спасбросок, навык, инициатива |
| `mobility_property` | скорость, полёт, телепортация |
| `utility_property` | чувства, свет, язык, внебоевая польза |
| `active_power` | отдельная активная способность |
| `signature_property` | один дополнительный слот особого комплексного свойства |

Новое усиление заменяет прежнее только в своей группе. Тир не является группой.
Старая группа `elemental_damage` считается совместимым псевдонимом
`additional_damage`, но в новом JSON не используется.

## 4. Запись усиления

Обязательные поля:

- `id`, `name`, `group`;
- `tier` — целое число от 1;
- `rank` — `standard`, `exceptional`, `unique` или `artifact`;
- `description` — полное игровое правило;
- `changes` — допустимые изменения цели, может быть пустым;
- `riders.activities`, `riders.effects`, `riders.items`.

Необязательные: `img`, `manual`, `attunement`, а для
`signature_property` — обязательные `signature_benefits`.

Усиление должно иметь механику хотя бы в одном из мест: `changes`,
`riders.activities`, `riders.effects` или `manual`. Неподдерживаемую часть
сохраняй в `description` и точном `manual`, не выдумывая системный ключ.

### Атомарность

Обычное усиление любого ранга содержит одну группу и одно самостоятельное
свойство. Несколько технических записей, обслуживающих одно свойство, допустимы:
например, `mgc` вместе с одной костью дополнительного урона.

Не объединяй под обычным усилением числовой бонус, отдельный урон,
сопротивление и активную силу.

Несколько связанных уникальных эффектов допустимы только для
`signature_property` ранга `exceptional`, `unique` или `artifact`.
Оно:

- содержит минимум два неповторяющихся `signature_benefits`;
- занимает только `signature_property`;
- не блокирует обычные группы;
- не используется как контейнер для набора стандартных `+1` и костей урона.

Если присутствует `occupies_groups`, он содержит только основную группу.

### Настройка

```json
{
  "attunement": {
    "weight": 2,
    "required": false
  }
}
```

`weight` — целое число `0–4`. Сумма активных весов `4` требует настройку.
`required: true` требует её независимо от суммы. Составной результат суммирует
вес самостоятельных компонентов.

## 5. Изменения цели

Каждый `change` имеет `key`, `mode`, `value`. Допустимые режимы:
`add`, `multiply`, `downgrade`, `upgrade`, `override`; `custom` запрещён.

| Назначение | `key` | Обычный `mode` |
|---|---|---|
| Свойство предмета | `system.properties` | `add` |
| Изображение | `img` | `override` |
| Владение | `system.proficient` | `upgrade` |
| Бонус оружия | `system.magicalBonus` | `override` |
| Бонус брони/щита | `system.armor.magicalBonus` | `override` |
| Дополнительный урон | `system.damage.parts` | `add` |
| Бонус урона | `system.damage.bonus` | `add` |
| Тип базового урона | `system.damage.base.types` | `add`/`override` |
| Типы урона activities | `system.damage.types` | `add`/`override` |
| Критический порог | `activities[attack].attack.critical.threshold` | `downgrade` |
| Дальность | `system.range.value` | `multiply` |
| Большая дальность | `system.range.long` | `multiply` |
| Название | `name` | `override` |
| Добавить описание | `system.description.value` | `add` |
| Максимум зарядов | `system.uses.max` | `override` |
| Восстановление | `system.uses.recovery` | `add` |
| Характеристика атаки | `activities[attack].attack.ability` | `override` |
| Бонус атаки | `activities[attack].attack.bonus` | `override` |
| Фиксированная атака | `activities[attack].attack.flat` | `override` |
| Бонус Сл | `activities[save].save.dc.bonus` | `add` |
| Формула Сл | `activities[save].save.dc.formula` | `override` |

Обычный `+1/+2/+3` находится только в `system.magicalBonus` оружия или
`system.armor.magicalBonus` брони/щита и не дублируется в атаке или уроне.
Дополнительный тип урона добавляется отдельной частью без среднего значения.
Если усиление делает предмет магическим, добавь `mgc`.

Не используй ключ, которого нет в этой таблице и разрешённом реестре билдера.

## 6. Rider-activities

Новая кнопка находится в `riders.activities` и использует сокращённый формат
`mechanics`:

```json
{
  "type": "save",
  "activity_name": "Огненная волна",
  "activation": {"type": "action", "value": 1},
  "save": {"ability": "dex", "dc": 15},
  "damage": [{"formula": "3d6", "type": "fire"}],
  "on_save": "half",
  "targeting": {
    "range": {"units": "self"},
    "template": {"type": "cone", "size": 15, "units": "ft"},
    "affects": {"type": "creature", "choice": false},
    "prompt": true
  },
  "uses": {
    "max": "3",
    "spent": 0,
    "recovery": [{"period": "lr", "type": "recoverAll"}]
  }
}
```

Правила:

- тип — `attack`, `save`, `damage`, `heal` или `utility`;
- `activity_name` уникален;
- обязательны `activation`, `targeting.range.units` и
  `targeting.affects.type`;
- каждая кнопка имеет собственные непустые `uses` либо осознанное
  `unlimited: true`;
- rider не расходует одноразовый усилитель;
- полное правило остаётся в `description`;
- формат механики бери из `docs/COMMON_JSON.md` и профильного документа;
- сложные ауры, триггеры, призыв, превращение и перемещение оставляй ручными.

## 7. Rider-effects

Постоянный эффект владельца: `transfer: true`, без `activity` и обычно без
длительности.

```json
{
  "name": "Ледяная защита",
  "transfer": true,
  "changes": [
    {"key": "system.traits.dr.value", "mode": "add", "value": "cold"}
  ]
}
```

Эффект выбранной цели: `transfer: false`, обязательная привязка к activity,
состояние или хотя бы один `change`.

```json
{
  "name": "Отравление",
  "status": "poisoned",
  "transfer": false,
  "activity": 0,
  "on_save": false,
  "duration": {"value": 1, "units": "minute"},
  "changes": []
}
```

`activity` — индекс, точное имя или поддерживаемый список селекторов.
`on_save: false` применяет эффект при провале. Общая аура или эффект от любой
существующей атаки без отдельного rider текущей схемой не поддерживается.

`riders.items` в схеме 7 всегда равен `[]`.

## 8. Bundles

`bundle` — 2–4 независимых атомарных усиления разных групп одного тира.
Он ссылается на компоненты через `enhancement_ids`. Группы компонентов не
пересекаются; после применения каждый компонент заменяется и удаляется
отдельно.

`bundle` не равен `signature_property`: первый устанавливает несколько
независимых Enchantment, второе остаётся одним неделимым особым свойством.

## 9. Пулы, усилители и таблицы

Каждый `pool` создаёт один расходный усилитель и одну RollTable.

- `tier` всех результатов совпадает с тиром пула;
- `target.item_types` использует `weapon`, `equipment`, `consumable`, `tool`
  или `loot`;
- `target.system_types` ограничивает фактический `system.type.value`; пустой
  массив разрешает любой подтип;
- `allow_magical: true` нужен, если предметы после первого усиления должны
  принимать следующие;
- не выдумывай `categories` и `properties`, если системный ID неизвестен;
- усилитель имеет `consumable_type: "trinket"`, одно использование и
  `autoDestroy: true`.

Каждый результат содержит ровно одну ссылку: `enhancement_id` или `bundle_id`.
Диапазоны `range` включительны, отсортированы, не пересекаются и без пропусков
покрывают весь `roll.domain`, обычно `1–100`. Все ссылки существуют, а один
компонент не повторяется в двух результатах одного пула.

## 10. Финальная проверка

Перед выдачей JSON пользователю в чате фактически запусти режим
`enhancement` или `enhancement_set` в `builder_app.py`.

Проверь:

- схема равна 7, корневой тип выбран верно;
- ID уникальны и все ссылки разрешаются;
- группы канонические, тиры и ранги согласованы;
- обычные усиления атомарны;
- `signature_property` имеет минимум два уникальных эффекта и занимает только
  собственную группу;
- ключи изменений разрешены, бонусы не продублированы;
- каждая rider-activity ограничена ресурсом либо явно безлимитна;
- эффекты связаны с правильными activities;
- `riders.items` пуст;
- пулы совместимы с целью и полностью покрывают диапазон;
- неподдерживаемая механика находится в `manual`, исполняемого кода нет.
