# Просмотр моделей NJ Design

Страница просмотра моделей Revit и DWG в браузере на базе Autodesk Viewer.
Ключ Autodesk остаётся на сервере-посреднике; каждая ссылка открывает только свою модель.

- `aps.py`: загрузка файла в Autodesk и запуск преобразования (`upload`, `status`, `list`).
- `worker/worker.js`: посредник (Cloudflare Worker): страница `/m/<id>` и запросы данных `/p/<id>/...`.
- `worker/dev.mjs`: локальный запуск посредника для проверки.

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
