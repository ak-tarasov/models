# Просмотр моделей NJ Design

Страница просмотра моделей Revit и DWG в браузере на базе Autodesk Viewer.
Ключ Autodesk остаётся на сервере-посреднике; каждая ссылка открывает только свою модель.

- `aps.py`: загрузка файла в Autodesk и запуск преобразования (`upload`, `status`, `list`).
- `worker/worker.js`: посредник (Cloudflare Worker): страница `/m/<id>` и запросы данных `/p/<id>/...`.
- `worker/dev.mjs`: локальный запуск посредника для проверки.
- `watch.py`: следит за папкой (смонтированный Google Диск): новый `.rvt` загружает, ждёт преобразования, создаёт ссылку и присылает её в Telegram.
- `cf.py`: размещение посредника в Cloudflare и ссылки на модели (`deploy`, `add`, `list`, `remove`).

## Публикация

1. Впишите в `.env` ключ Cloudflare (`CF_API_TOKEN`, шаблон Edit Cloudflare Workers).
2. `python3 cf.py deploy`: в ответе адрес посредника.
3. `python3 cf.py add <urn> "Название"`: в ответе ссылка на модель.
4. `python3 cf.py view <id> '{"dir": [-1, 1, 1.3], "zoom": 1.1, "box": [x1, y1, z1, x2, y2, z2], "hide": [dbId, ...]}'`: с какой стороны и насколько крупно открывать модель, какую область показать и какие элементы скрыть (все поля необязательны).
5. `python3 cf.py remove <id>`: ссылка перестаёт работать.

## Папка с моделями

1. В `.env`: `WATCH_DIR=<папка>`; необязательно `WATCH_MONTH_LIMIT` (20), `WATCH_NOTIFY_TOPIC` (Модели), `WATCH_WAIT` (600 с).
2. `python3 watch.py --dry-run`: что будет загружено; `python3 watch.py`: один проход (запускать по расписанию).
3. Что уже обработано и сколько преобразований израсходовано за месяц: `watch.state.json`. Тот же файл дважды не загружается.
4. Проверки: `python3 -m unittest discover -s tests`.

## Локальный запуск

1. Скопируйте `.env.example` в `.env` и впишите ключ приложения Autodesk Platform Services.
2. `python3 aps.py upload model.rvt`: в ответе будет `urn`.
3. `python3 aps.py status <urn>`: дождитесь `success`.
4. Создайте `models.local.json`: `{"myid12345": {"urn": "<urn>", "name": "Название"}}`.
5. `node worker/dev.mjs 8787` и откройте `http://127.0.0.1:8787/m/myid12345`.

Нужны Python 3.9+ и Node 20+, сторонних пакетов нет.

## Вставка на сайт

```html
<iframe src="https://<адрес-посредника>/m/<id>" style="width:100%;height:600px;border:0" allowfullscreen></iframe>
```
