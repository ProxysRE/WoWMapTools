# Локальный исполнитель GitHub Actions

Это инструкция существующего workflow **Render on local Windows runner**.
Он обрабатывает `requests/active.json` с **импортированными PNG** из `catalog.json`.
Сам рендерер поддерживает также ZIP/M2, но этот workflow не передаёт `--packages`,
не собирает население и не выполняет экспорт сцен Foundry.

## Подготовка

- [Установите программу](INSTALLATION.md) и проверьте ручной рендер.
- ПК Windows должен быть включён и подключён к сети.
- Постоянные ресурсы храните вне рабочей папки runner.
- Workflow запускает код репозитория на ПК: разрешайте доступ только доверенным участникам.

## Настройка

1. Импортируйте PNG в постоянную папку:

   ```console
   python -m wowmap import-png "D:\Exports\PNG.zip" --assets "D:\WoWMapTools\Assets"
   ```

2. В репозитории откройте Settings → Actions → Runners → New self-hosted runner.
   Выберите Windows x64 и выполните команды GitHub локально. Токен не передавайте в чат.
3. Добавьте метку `wowmap`; стандартные — `self-hosted`, `Windows`, `X64`.
4. В Settings → Secrets and variables → Actions → Variables задайте:

   | Переменная | Значение |
   |---|---|
   | `WOWMAP_ASSETS` | Абсолютный путь к папке с `catalog.json` |
   | `ENABLE_LOCAL_RENDER` | `true` |

5. Запустите runner. Ресурсы не размещайте в `_work`: checkout может их очистить.
6. Выберите Actions → Render on local Windows runner → Run workflow.
   Изменения `requests/active.json` в main также запускают его.

Результат — артефакт `wowmap-render`, срок хранения 7 дней.
Workflow не запускается на pull request. При выключенном runner задание ждёт;
`ENABLE_LOCAL_RENDER` отключает новые задания. Он не открывает порт и не является
постоянно доступным сервером. Загрузка результатов подчиняется доступу к репозиторию;
для непубличных карт нужен соответствующий доступ или приватный репозиторий.

Сам упаковщик MPQ, поиск пакетов, превью моделей и пакетный Builder — отдельные
инструменты, перечисленные в [README](README.md). Наличие этого шаблона не означает,
что runner уже установлен на пользовательском ПК.
