# Совместимость оружия и экипировки с усилениями

Этот короткий контракт применяется одинаково к оружию и экипировке.
Он не описывает создание усилителей, усилений, пулов или таблиц.
Для них по явному запросу используй `ENHANCEMENTS_JSON.md`.

## Выбор режима

- `locked` — завершённый артефакт или уникальный именной предмет;
- `open` — обычный предмет или основа для крафта;
- `restricted` — предмет, которому явно разрешён ограниченный набор групп.

Для `locked` укажи пустые `allowed_groups` и `native_properties`, а также
краткую `reason`. Классифицировать все врождённые свойства такого
предмета не нужно.

Для `open` и `restricted` занеси уже занятые врождёнными свойствами
группы в `native_properties`. Для `restricted` перечисли допустимые
группы в `allowed_groups`. Механика самих свойств по-прежнему должна быть
реализована в обычных полях предмета.

Допустимые группы: `numeric_bonus`, `additional_damage`,
`offensive_property`, `defensive_property`, `attribute_property`,
`mobility_property`, `utility_property`, `active_power`, `signature_property`.

## Особый материал

`material_property` заполняй только при явно указанном особом материале.
Он не занимает обычную группу или `signature_property`. Его фактические
эффекты также реализуй на самом предмете.

## Каркас

```json
{
  "enhancement_policy": {
    "mode": "locked",
    "allowed_groups": [],
    "native_properties": [],
    "material_property": null,
    "reason": "Завершённый уникальный предмет."
  }
}
```
