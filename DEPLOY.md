# Деплой backend Fresso

Готовые конфиги для публикации Flask-backend (`backend.py`, приложение `app`) на
HTTPS-домен, чтобы мобильное приложение могло к нему обращаться.

В наборе:

| Файл | Для чего |
|---|---|
| `Dockerfile` | Универсальный образ (Python 3.11 + gunicorn). Работает на Railway, Render, Fly.io, любом Docker-хосте |
| `.dockerignore` | Что не класть в образ (`.env`, локальная БД, кэш) |
| `Procfile` | Команда запуска для Railway/Heroku-совместимых платформ (без Docker) |
| `render.yaml` | Blueprint для Render (сервис + постоянный диск под SQLite) |
| `railway.json` | Конфиг сборки/запуска для Railway |
| `fly.toml` | Конфиг для Fly.io (с volume и health-check) |

Точка запуска в проде — **gunicorn**, а не `app.run()` (он используется только локально на порту 5001).

---

## Переменные окружения (одинаковы для всех платформ)

| Переменная | Обязательна | Описание |
|---|---|---|
| `SECRET_KEY` | да (прод) | Подпись сессий. Сгенерировать: `python3 -c "import secrets; print(secrets.token_hex(32))"`. На Render генерируется автоматически |
| `FLASK_ENV` | рекомендуется | `production` — отключает dev-режим |
| `CORS_ORIGINS` | да | Разрешённые источники через запятую, напр. `https://fresso.app`. Для мобильного Expo-клиента CORS не требуется, но укажите домен веб-версии, если она есть |
| `OPENAI_API_KEY` | опционально | Перевод рецептов и AI-фолбэк извлечения/нутриентов |
| `USDA_API_KEY` | рекомендуется | Расчёт нутриентов (без ключа — `DEMO_KEY`, 30 запросов/час) |
| `DATABASE_URL` | опционально | Не задавайте — будет SQLite на диске. Для Postgres: `postgresql+psycopg2://user:pass@host:5432/db` |
| `PORT` | авто | Railway/Render/Fly подставляют сами; gunicorn его использует |

> ⚠️ Не коммитьте `.env` в git. Задавайте секреты в дашборде платформы.

---

## Вариант 1 — Railway (быстрее всего)

1. Запушьте репозиторий на GitHub.
2. Railway → **New Project → Deploy from GitHub repo** → выберите репозиторий, корень — папка `backend`.
3. Railway увидит `Dockerfile` и `railway.json` и соберёт образ.
4. Во вкладке **Variables** добавьте: `SECRET_KEY`, `FLASK_ENV=production`, `CORS_ORIGINS`, `OPENAI_API_KEY`, `USDA_API_KEY`.
5. Для сохранности SQLite между деплоями: **Add Volume** → mount path `/app/instance`.
6. Railway выдаст публичный HTTPS-домен (Settings → Networking → Generate Domain).

## Вариант 2 — Render (постоянный диск из коробки)

1. Запушьте репозиторий на GitHub.
2. Render → **New → Blueprint** → выберите репозиторий. Он подхватит `render.yaml`
   (сервис `fresso-backend` + диск `fresso-data` на `/app/instance`).
3. В дашборде заполните секреты `OPENAI_API_KEY`, `USDA_API_KEY`, `CORS_ORIGINS`
   (`SECRET_KEY` сгенерируется автоматически).
4. Deploy. Health-check бьёт в `/api/health`.

> На бесплатном плане сервис «засыпает» при простое — для прода берите `starter`.

## Вариант 3 — Fly.io (регионы / близость к пользователям)

```bash
fly launch --no-deploy            # создаст приложение, оставьте fly.toml
fly volumes create fresso_data --size 1 --region fra
fly secrets set SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") \
                FLASK_ENV=production \
                OPENAI_API_KEY=sk-... \
                USDA_API_KEY=... \
                CORS_ORIGINS=https://fresso.app
fly deploy
```
Регион `fra` (Франкфурт) или `ams` (Амстердам) — ближе к РФ/ЕС.

## Вариант 4 — свой VPS (Docker)

```bash
docker build -t fresso-backend ./backend
docker run -d --name fresso \
  -p 5001:5001 \
  -v /opt/fresso/instance:/app/instance \
  -e SECRET_KEY=... -e FLASK_ENV=production \
  -e OPENAI_API_KEY=... -e USDA_API_KEY=... -e CORS_ORIGINS=https://fresso.app \
  fresso-backend
```
Спереди поставьте **Caddy** или **Nginx + Let's Encrypt** для HTTPS (Apple ATS требует HTTPS).

---

## Локальная проверка образа (перед деплоем)

```bash
cd backend
docker build -t fresso-backend .
docker run --rm -p 5001:5001 -e FLASK_ENV=development fresso-backend
# проверка:
curl http://localhost:5001/api/health
```

---

## Перенос существующей БД

Локальная БД лежит в `instance/bunnykitchen-complete.db`. Чтобы перенести данные в прод:

- **SQLite на диске:** скопируйте файл на persistent volume платформы
  (Railway/Render — через их CLI/Shell; Fly — `fly ssh sftp shell`).
- **Переезд на Postgres:** поднимите managed Postgres у платформы, задайте `DATABASE_URL`,
  затем перенесите данные (экспорт из SQLite → импорт в Postgres).
  Postgres рекомендуется при росте нагрузки и нескольких воркерах.

---

## После деплоя — подключите мобильное приложение

Возьмите публичный HTTPS-URL и пропишите его в мобильном клиенте:

```bash
# в fresso-mobile:
EXPO_PUBLIC_API_URL=https://<ваш-домен>/api/v1 npx expo start
```
или впишите URL в `fresso-mobile/app.json` → `expo.extra.apiUrl`.
