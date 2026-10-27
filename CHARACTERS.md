# Сборка внешности и снаряжения персонажей WotLK

Явные параметры `character` и Item ID в `equipment` собирают тело, одежду и
отдельные модели экипировки из клиента **3.3.5.12340**. Выход — прозрачный токен
сверху и отдельный портрет анфас. Foundry показывает WebP, не интерактивную M2.

## Раса, пол и внешность

Все десять игровых рас поддержаны в обоих полах: `human`, `orc`, `dwarf`,
`nightelf`, `scourge`, `tauren`, `gnome`, `troll`, `bloodelf`, `draenei`.
Также доступны гоблины обоих полов (`goblin`), наги обоих полов (`naga_`),
мужские `felorc`, `broken`, `skeleton`, `vrykul`, `tuskarr`, `foresttroll`,
`taunka`, `northrendskeleton`, `icetroll`: всего **33 существующих тела**
в проверенном наборе. Записи женских NPC-рас без ресурсов не считаются поддержкой.

`gender` — `male` / `female`; `skin`, `face`, `hair_style`, `hair_color`,
`facial_hair` — индексы DBC. По умолчанию кожа/лицо/цвет/особенности лица 0,
причёска 1 у игровых рас, 0 у дополнительных NPC-рас. Неподдержанный стиль
не заменяется случайным похожим. У NPC меньше вариантов и встречаются фиктивные
ссылки DBC: отсутствующие необязательные накладки лица/скальпа перечисляются
в `omitted_optional_overlays`. Отсутствующая основная кожа останавливает сборку.
Проверка доступности относится к конкретному телу и конкретному предмету.

```console
python -m wowmap.characters options --dbc-assets D:\WoWAssets\DBC --model-assets D:\WoWAssets\Characters
```

Команда выводит JSON с наличием моделей, доступными индексами кожи, записями
причёсок/особенностей лица, наличием атласа одежды и точками крепления.
Списки DBC не гарантируют наличие каждого ресурса каждого стиля: итоговая сборка
проверяет их. Северный скелет использует отдельную кожу без атласа одежды;
на нём разрешены подходящие крепления, текстурная одежда отклоняется.

## Слоты

| Слот | Ключ equipment | InventoryType |
|---|---|---|
| Рубаха | `shirt` | 4 |
| Нагрудник / мантия | `chest` | 5 / 20 |
| Штаны | `legs` | 7 |
| Сапоги | `boots` | 8 |
| Перчатки | `gloves` | 10 |
| Пояс | `belt` | 6 |
| Наручи | `bracers` | 9 |
| Шлем | `head` | 1 |
| Наплечники | `shoulders` | 3 |
| Правая рука / основное оружие | `main_hand` | 13 / 17 / 21 / 15 / 25 / 26 |
| Левая рука / щит / предмет | `off_hand` | 13 / 14 / 22 / 23 |

Значение — **Item ID клиента**, не Display ID и не ID предмета Foundry.
Item.dbc связывает его с ItemDisplayInfo. Двуручное оружие несовместимо с
`off_hand`. Неверный слот, отсутствующая модель/текстура/точка крепления или
неподдержанный материал дают ошибку до публикации результатов Builder.

Одежда накладывается по исходным регионам атласа с корректной альфой BLP2.
Мантия выбирает длинную геометрию; перчатки убирают конфликтующие манжеты.
Нижнее бельё остаётся под одеждой, где есть исходный слой. У тауренов сохраняются
копыта, у троллей/дренеев и соответствующих NPC — открытые ступни; нижняя часть
голени может быть одета. Нага не получает человеческие штаны или сапоги.
Отсутствующие родные варианты геометрии копыт отражаются в отчёте.

## Отдельные модели

Шлем использует `ClientPrefix` расы из ChrRaces и суффикс пола, например `_hum`.
Чужая модель шлема не подставляется вместо отсутствующей: у большинства
дополнительных NPC-рас нет собственных вариантов обычных шлемов.
HelmetGeosetVisData управляет скрытием волос, особенностей лица и ушей по маске
расы и полу. Наплечники используют обе исходные модели независимо.

Точки M2: шлем 11, левое/правое плечо 6/5, правая/левая ладонь 1/2, щит 0.
Позиции читаются через attachment lookup; в исходной ненастроенной позе матрицы
костей единичные. Тело и все крепления собираются в общую геометрию **до**
поворота камеры, кадрирования и прохода глубины. Изображения предметов не клеятся
поверх готового портрета. Источники моделей, SKIN и текстур попадают в SHA-отчёт.

## Задание и запуск

В `appearance` пакетного Builder вместо `display_id`:

```json
{
  "character": {
    "race": "orc", "gender": "female", "skin": 0, "face": 0,
    "hair_style": 1, "hair_color": 0, "facial_hair": 0
  },
  "equipment": {
    "chest": 285, "legs": 286, "boots": 287, "gloves": 718,
    "head": 3836, "shoulders": 4725, "main_hand": 25, "off_hand": 143
  },
  "size": 512, "portrait_size": 768
}
```

```console
python -m wowmap.characters search --dbc-assets D:\WoWAssets\DBC --slot head --query plate --limit 20
python -m wowmap.characters render --dbc-assets D:\WoWAssets\DBC --model-assets D:\WoWAssets\Characters --request requests/appearance.json --out output/outfit
python tools/build_foundry_batch.py requests/builder/all-races.json --dbc-assets D:\WoWAssets\DBC --model-assets D:\WoWAssets\Characters --out output/all-races
```

Поиск использует английские имена моделей, текстур и иконок, не локализованные
названия. Отдельный файл `--request` содержит объект из примера выше.
Ракурсы, установка и пути — [TOKENS.md](TOKENS.md), [INSTALLATION.md](INSTALLATION.md).
`display_id` и `character` несовместимы; существующие creature-модели не одеваются
автоматически. **Внешность не меняет механику:** Item ID не добавляет предмет в
инвентарь, КД, атаки или урон. Боевой лист создаётся обычным Builder отдельно.

`requests/builder/all-races.json` — 33 технических NPC, 66 изображений, КД 10,
1 хит, без атак. Одинаковый демонстрационный комплект проверен на игровых расах.
Для дополнительных NPC неподходящие части исключены **при подготовке задания**
и перечислены в отчёте демонстрации; renderer не удаляет запрошенные предметы.
`tools/prepare_character_demo.py` воспроизводит проверку ресурсов и подготовку
этого задания; его `--audit` задаёт путь отчёта. Старый пример
`requests/builder/human-outfits.json` остаётся четырьмя образцами текстурной одежды.

Нужны ZIP выбранных `character-*`, `item-texturecomponents-*`,
`item-objectcomponents-*`, дополнительные creature-текстуры, на которые ссылается
конкретное тело, и DBC. Таблицы: CharSections, CharHairGeosets,
CharacterFacialHairStyles, Item, ItemDisplayInfo, ChrRaces (69 полей),
HelmetGeosetVisData (8 полей), плюс стандартные таблицы существ TokenAssets.
ZIP кладутся в корень набора или `packages/`. Оригиналы не меняются и не входят
в публичный репозиторий. Программа читает уже доступный приватный набор ресурсов.

## Границы реализации

Позы и анимации отложены. Руки остаются раскрытыми в исходной позе; оружие не
получает автоматический хват и не переводит тело в боевую стойку. Частицы,
зачарования и ItemVisual не воспроизводятся (ID сохранены в отчёте); статическая
геометрия предмета отображается. Плащи, гербовые накидки, отдельные модели поясов,
сборка по CreatureDisplayInfoExtra и новые расы из последующих клиентов не входят
в этот этап. Не каждый предмет совместим с каждым телом.

## Проверка и источники

Тесты проверяют регионы/альфу атласа, геометрию одежды, выбор шлема по расе/полу,
маску ушей, левое/правое плечо, привязку оружия/щита, общую сцену рендера, неверные
и отсутствующие ресурсы, оба ракурса, Builder и отказ без частичного вывода.
Реальная проверка ресурсов дополняет синтетические тесты; установленная Foundry
проверяется мастером. Ранее найденная отдельная плоскость альфы palettized BLP2
обрабатывается общим декодером, старые установленные WebP сами не обновляются.

- WoWDBDefs: [ChrRaces](https://github.com/wowdev/WoWDBDefs/blob/master/definitions/ChrRaces.dbd),
  [HelmetGeosetVisData](https://github.com/wowdev/WoWDBDefs/blob/master/definitions/HelmetGeosetVisData.dbd),
  [CharSections](https://github.com/wowdev/WoWDBDefs/blob/master/definitions/CharSections.dbd),
  [CharHairGeosets](https://github.com/wowdev/WoWDBDefs/blob/master/definitions/CharHairGeosets.dbd),
  [CharacterFacialHairStyles](https://github.com/wowdev/WoWDBDefs/blob/master/definitions/CharacterFacialHairStyles.dbd),
  [ItemDisplayInfo](https://github.com/wowdev/WoWDBDefs/blob/master/definitions/ItemDisplayInfo.dbd).
  Используются секции **3.3.5.12340**, включая отсутствие ID в CharacterFacialHairStyles.
- Legacy WoW Model Viewer: [сборка персонажа](https://github.com/wowmodelviewer/wowmodelviewer/blob/8207caf5449997409e7c2c8fe05b229c7ab19564/src/charcontrol.cpp),
  [точки крепления](https://github.com/wowmodelviewer/wowmodelviewer/blob/8207caf5449997409e7c2c8fe05b229c7ab19564/src/model.cpp).
