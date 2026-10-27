# Одежда на базовых людских моделях

Первый рабочий этап: мужское и женское тело Human из WotLK 3.3.5a, кожа, лицо,
причёска, цвет волос и особенности лица, затем оригинальные текстуры одежды и
соответствующие части геометрии. Выход — отдельные прозрачные WebP токена сверху
и портрета анфас. Это не интерактивная M2 в Foundry.

## Поддержка

| Слот | Ключ equipment | InventoryType |
|---|---|---|
| Рубаха | `shirt` | 4 |
| Нагрудник / мантия | `chest` | 5 / 20 |
| Штаны | `legs` | 7 |
| Сапоги | `boots` | 8 |
| Перчатки | `gloves` | 10 |
| Пояс | `belt` | 6 |
| Наручи | `bracers` | 9 |

Значение — **Item ID клиента**, не Display ID и не ID предмета Foundry.
Item.dbc связывает его с ItemDisplayInfo, текстурами и флагами геометрии.
Неправильный слот, неизвестный ID, отсутствующий ресурс или неподдержанная часть
останавливают сборку. Мантия использует длинную геометрию; расширенные перчатки
скрывают несовместимые манжеты. Нижнее бельё сохраняется под одеждой.
Невидимые части исключаются из кадрирования.

## Задание

В `appearance` пакетного Builder вместо `display_id`:

```json
{
  "character": {
    "race": "human", "gender": "male", "skin": 0, "face": 0,
    "hair_style": 1, "hair_color": 0, "facial_hair": 0
  },
  "equipment": {"shirt": 2576, "legs": 10035, "boots": 43},
  "size": 512, "portrait_size": 768
}
```

Пол — `male` или `female`. Числа внешности — индексы DBC, не произвольные цвета.
По умолчанию мужское тело, кожа/лицо/цвет волос/особенности лица 0, причёска 1.
Остальные параметры ракурсов — [TOKENS.md](TOKENS.md).
`display_id` и `character` несовместимы. Путь `display_id` не одевает готовые
creature-модели: используется базовое тело `character/human/...`.

**Внешность и механика независимы.** `equipment` не добавляет предметы в инвентарь,
не меняет КД, урон или правила. Для игрового NPC его предметы отдельно создаются
настоящим Builder, а визуальные Item ID выбираются для изображения.

## Поиск и сборка

```console
python -m wowmap.characters search --dbc-assets D:\WoWAssets\DBC --slot chest --query "mail" --limit 20
python -m wowmap.characters render --dbc-assets D:\WoWAssets\DBC --model-assets D:\WoWAssets\Characters --request requests/appearance.json --out output/outfit
python tools/build_foundry_batch.py requests/builder/human-outfits.json --dbc-assets D:\WoWAssets\DBC --model-assets D:\WoWAssets\Characters --out output/human-outfits
```

Поиск основан на английских именах текстур и иконок, не локализованных именах
предметов; результаты отдельно проверяются сборкой. Для одиночного рендера
`--request` — JSON с объектом из примера выше; файл создаёт автор задания.

Пакетный пример содержит четыре технических NPC: рабочая одежда, кольчужный
комплект и две мантии. У трёх мужских образцов одинаковые тело, лицо и волосы,
меняется только экипировка; четвёртый использует женское тело. Все характеристики
10, КД 10, 1 хит, без атак и способностей. Это проверка внешности, не боевые листы.

Ресурсы: `character-human-14d31d98-001.zip`, нужные части
`item-texturecomponents-f3781f92-*.zip` и DBC. Используются CharSections,
CharHairGeosets, CharacterFacialHairStyles, ItemDisplayInfo и Item, плюс два
стандартных DBC существ из TokenAssets. ZIP можно положить в корень одного набора
или в `packages/`; программа не скачивает их сама.

Пути токенов, портретов и установка — [INSTALLATION.md](INSTALLATION.md).
Отчёт хранит Item/Display ID, выбранную геометрию, слои и SHA-256 исходников/DBC.
Атлас вычисляется в памяти; оригиналы не меняются.

## Ограничения

Пока нет других рас, шлемов, наплечников, оружия/щитов, плащей, гербовых накидок,
отдельных моделей поясов, эффектов предметов и автосборки по CreatureDisplayInfoExtra.
Предмет с отдельной моделью или визуальным эффектом отклоняется, даже если слот
поддержан. Не все Item ID пригодны. Позы остаются отложены; используется исходная
геометрия. Следующий слой — отдельные модели, точки крепления и скрытие геометрии.

## BLP2 и проверка

При сборке найден дефект прежнего декодирования: у palettized BLP2 альфа хранится
после индексов палитры. Путь Pillow брал альфу палитры, из-за чего части одежды
могли исчезнуть. Общий декодер теперь читает 0/1/4/8-битную плоскость, проверяет
границы mip и размеры до декодирования. Остальные форматы остаются на Pillow.
Исправление действует на модели и иконки, версия кэша спрайтов повышена.
Установленные изображения автоматически не обновляются.

Проверки охватывают альфу, наложение без изменения оригиналов, выбор геометрии,
неверные слоты/ID, оба ракурса, реальный Builder и отказ без частичного вывода.
Три прежних лесных NPC с шестью изображениями и семью иконками пересобраны:
все 13 файлов графики совпали побайтно. Игровая проверка новых человеческих
образцов в установленном Foundry остаётся за мастером.

## Источники форматов

- WoWDBDefs: [CharSections](https://github.com/wowdev/WoWDBDefs/blob/master/definitions/CharSections.dbd),
  [CharHairGeosets](https://github.com/wowdev/WoWDBDefs/blob/master/definitions/CharHairGeosets.dbd),
  [CharacterFacialHairStyles](https://github.com/wowdev/WoWDBDefs/blob/master/definitions/CharacterFacialHairStyles.dbd),
  [Item](https://github.com/wowdev/WoWDBDefs/blob/master/definitions/Item.dbd),
  [ItemDisplayInfo](https://github.com/wowdev/WoWDBDefs/blob/master/definitions/ItemDisplayInfo.dbd).
  Используются секции для **3.3.5.12340**, включая отсутствие ID в
  CharacterFacialHairStyles этой версии.
- Legacy WoW Model Viewer: [регионы атласа](https://github.com/wowmodelviewer/wowmodelviewer/blob/8207caf5449997409e7c2c8fe05b229c7ab19564/src/charcontrol.h)
  и [порядок одежды / геометрия](https://github.com/wowmodelviewer/wowmodelviewer/blob/8207caf5449997409e7c2c8fe05b229c7ab19564/src/charcontrol.cpp).
- [Pillow: BLP](https://github.com/python-pillow/Pillow/blob/main/src/PIL/BlpImagePlugin.py),
  [формат BLP2](https://wowdev.wiki/BLP).
