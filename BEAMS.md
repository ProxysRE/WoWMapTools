# Лучи WoW

Книжный модуль WoW DnD5e 0.40.25 дополняет прежние снаряды четырьмя лучевыми
профилями. Это короткий визуальный импульс между двумя точками, а не постоянный
канал на всю минуту концентрации. Длительные связи потребуют отдельного жизненного
цикла и снятия эффекта.

| Профиль | SpellChainEffects ID | Исходная текстура | Направление рисунка |
|---|---:|---|---|
| wow.frost.beam | 326 | spells/textures/beam_waterblue.blp | От источника |
| wow.shadow.beam | 10 | textures/spellchaineffects/beam_purple.blp | От источника |
| wow.nature.beam | 5 | textures/spellchaineffects/soulbeam.blp | От источника |
| wow.drain.beam | 5 | textures/spellchaineffects/soulbeam.blp | К источнику |

Профиль — выбранное художественное соответствие нашей способности; таблица не
утверждает, что именно это исходное Spell ID игры использует ту же комбинацию.
RGB и alpha взяты из выбранной записи DBC, текстуры оригинальные.

```console
python -m wowmap.beams --assets D:\WoWAssets --out output/frost-beam --profile wow.frost.beam
```

Нужны пакеты dbfilesclient (SpellChainEffects), spells/textures и
textures/spellchaineffects, а также ffmpeg с libvpx-vp9. Пустой выходной каталог,
30 кадров/с, 512×128, цикл одна секунда, VP9 с alpha. Отчёт содержит записи
происхождения и SHA-256. Готовые медиа и приватные ресурсы в git не сохраняются.

DBC 3.3.5 имеет 48 логических полей в **177 байтах**: Alpha/Red/Green/Blue/BlendMode
упакованы как пять байт на смещении 156. Универсальный доступ по column*4 здесь
не подходит. Рендерер требует именно эту схему и additive-режим 3. Чёрная подложка
переводится в прозрачность. Зеркальное повторение UV убирает шов между краями
старых непериодических полос. Скорость UV, изгиб и сужение концов адаптированы
к виду сверху; полного воспроизведения joint/wave/flicker/branching нет.

Адаптер Sequencer 3.6.11 использует stretchTo с onlyX и фиксированную Y scale.
size() в его ветке stretch не применяется, поэтому толщина задаётся явно через
scale({x:1,y:gridSize*heightCells/fileHeight}). template задаёт нулевые отступы
начала/конца. Нет moveTowards, перемещения токенов, persist или игровой автоматики.
Источник и конечная точка фиксируются при запуске; длительность 900 мс.

Предыдущие 95 назначений сохранены. Новые 13: холодные лучи; первоначальное
применение слабости, болезни и пытки разума; атака, повтор после промаха и
поддержание похищения жизни. Кнопки лечения и повторные спасброски исключены.
Многолучевой «Палящий луч» и цепные прыжки пока не назначены.

Проверки формата DBC, цикла и прозрачности — tests/test_beams.py. Адаптер книжного
модуля проверяется в его исходниках имитацией Foundry/Sequencer. Живая проверка
новых лучей остаётся отдельным шагом.

Источники контрактов:
[SpellChainEffects 3.3.5](https://github.com/wowdev/WoWDBDefs/blob/master/definitions/SpellChainEffects.dbd),
[Sequencer 3.6.11](https://github.com/fantasycalendar/FoundryVTT-Sequencer/blob/3.6.11/src/canvas-effects/canvas-effect.js).
