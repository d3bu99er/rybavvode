# FishingMap MVP

Сервис для парсинга публичных сообщений форума про платные водоемы, геокодинга топиков и отображения активности на карте.

Проект включает:
- фоновый сбор данных с форума;
- хранение в PostgreSQL с дедупликацией;
- скачивание вложений-изображений;
- карту с просмотром сообщений по точкам;
- админ-панель для модерации постов, координат и вложений.

## Что делает проект

- Парсит топики и сообщения из ветки `FORUM_ROOT_URL` (по умолчанию Rusfishing).
- Сохраняет:
  - `sources`
  - `topics`
  - `posts`
  - `post_attachments`
- Выполняет геокодинг `place_name` топиков через Yandex или Google API.
- Строит карту на `folium`:
  - `legacy` режим;
  - `v2` режим (по умолчанию через `MAP_UI_V2=true`).
- В UI сообщений:
  - превью изображений кликабельно;
  - при клике открывается оригинал на той же странице (lightbox);
  - цитаты в тексте сообщений выделяются отдельным блоком.
- Вложения:
  - скачиваются только изображения;
  - не-image вложения очищаются (в фоне и вручную из админки).

## Технологии

- Python 3.11+
- FastAPI + Jinja2
- SQLAlchemy 2.x + Alembic
- PostgreSQL 16
- APScheduler
- httpx + BeautifulSoup4
- folium
- Docker + Docker Compose

## Структура сервисов

- `db` — PostgreSQL.
- `app` — FastAPI приложение:
  - на старте выполняет `alembic upgrade head`;
  - запускает `uvicorn`;
  - поднимает периодическую задачу синхронизации.

`docker-compose.yml`:
- публикует `8000` (app) и `5432` (db);
- монтирует `./data -> /app/data`;
- volume `pg_data` для БД.

## Быстрый старт (Docker)

1. Скопируйте env:

```bash
cp .env.example .env
```

2. Заполните `.env`:
- `SECRET_KEY`
- `ADMIN_USER`, `ADMIN_PASSWORD`
- геокодер: `YANDEX_GEOCODER_API_KEY` или `GOOGLE_GEOCODING_API_KEY`
- (опционально) форумная авторизация: `FORUM_USERNAME`, `FORUM_PASSWORD`, `FORUM_LOGIN_URL`

3. Запустите:

```bash
docker compose up -d --build
```

4. Проверьте:

```bash
docker compose ps
curl -f http://127.0.0.1:8000/health
```

## Основные URL

- Карта: `http://localhost:8000/`
- Админ-логин: `http://localhost:8000/admin/login`
- API posts: `http://localhost:8000/api/posts`

## Режимы UI карты

- По умолчанию режим определяется `MAP_UI_V2`.
- Принудительное переключение query-параметром:
  - `/?ui=v2`
  - `/?ui=legacy`

Поддерживаемые параметры:
- `period=24h|7d|30d`
- `q=<поиск>`
- `limit=<1..500>`

## Авторизация на форуме и загрузка вложений

Поддерживаются 2 режима:

1. Статическая cookie:
- задайте `FORUM_SESSION_COOKIE`.

2. Автологин:
- задайте `FORUM_LOGIN_URL`, `FORUM_USERNAME`, `FORUM_PASSWORD`.

Логика автологина:
- валидирует, что сессия действительно авторизована;
- детектирует редирект обратно на логин;
- учитывает наличие `xf_user`/маркеров авторизации;
- при rate limit логина ставит cooldown перед повтором;
- пишет диагностический warning с причиной.

При ошибках скачивания вложений по `401/403` в логах выводится подробная причина (`reason=...`, маркеры, content-type, body-preview).

## Вложения

Хранение:
- локальная директория: `ATTACHMENTS_DIR` (по умолчанию `data/attachments`);
- раздача через FastAPI static: `/media/attachments/...`.

Логика:
- скачиваются только `is_image=true` вложения;
- изображения детектируются по mime/name/url;
- для UI формируются пары `preview -> original` (если доступны);
- non-image файлы удаляются через cleanup.

Админ-действия:
- `POST /admin/posts/{post_id}/attachments/retry`
- `POST /admin/attachments/retry-missing`
- `POST /admin/attachments/cleanup-non-image`

## API

Публичные:
- `GET /health`
- `GET /api/posts?since=&has_geo=true&include_deleted=false&q=&limit=100&offset=0`
- `GET /api/posts/{post_id}`
- `GET /api/topics/{topic_id}`
- `GET /api/topics/{topic_id}/messages?page=1&per_page=15`

Веб:
- `GET /` — страница карты.

## Админка

- `GET /admin/login`, `POST /admin/login`, `GET /admin/logout`
- `GET /admin/posts`
  - soft delete / restore постов.
- `GET /admin/topics`
  - ручное обновление координат.
- `GET /admin/attachments`
  - фильтр missing;
  - batch retry missing;
  - cleanup non-image.

## Фоновые задачи

Запускаются в `app.main`:
- периодический scrape-job каждые `FETCH_INTERVAL_SECONDS`;
- немедленный первый запуск при старте приложения.

## Переменные окружения (ключевые)

Полный список: `.env.example`

Базовые:
- `APP_ENV`, `APP_HOST`, `APP_PORT`
- `SECRET_KEY`
- `DATABASE_URL`

Форум/парсинг:
- `FORUM_ROOT_URL`
- `FORUM_SOURCE_NAME`
- `MAX_FORUM_PAGES`
- `MAX_TOPIC_PAGES`
- `FETCH_INTERVAL_SECONDS`
- `MAX_CONCURRENCY`
- `REQUESTS_PER_SECOND`
- `HTTP_TIMEOUT_SECONDS`

Авторизация форума:
- `FORUM_LOGIN_URL`
- `FORUM_USERNAME`
- `FORUM_PASSWORD`
- `FORUM_SESSION_COOKIE_NAME`
- `FORUM_SESSION_COOKIE`

Вложения:
- `DOWNLOAD_ATTACHMENTS`
- `ATTACHMENTS_DIR`

Геокодинг:
- `GEOCODER_PROVIDER=google|yandex`
- `GOOGLE_GEOCODING_API_KEY`
- `YANDEX_GEOCODER_API_KEY`
- `GEOCODE_TTL_DAYS`
- `MIN_GEO_CONFIDENCE`

UI/админ:
- `MAP_UI_V2`
- `ADMIN_USER`
- `ADMIN_PASSWORD`

## Миграции

В проекте:
- `0001_init`
- `0002_post_attachments`

Применение:

```bash
docker compose exec app alembic upgrade head
```

## Тесты

Запуск:

```bash
pytest
```

Покрыты базовые сценарии:
- soft delete/restore;
- mapping постов по координатам топика;
- ручное обновление координат;
- нормализация `place_name`;
- мок геокодера.

## Полезные команды эксплуатации (Linux)

Логи загрузки вложений/автологина:

```bash
docker compose logs app --since=30m 2>&1 | grep -Ei "Attachment download|Forum login|unauthorized|retry_after"
```

Проверка env внутри контейнера:

```bash
docker compose exec app sh -lc 'for k in DOWNLOAD_ATTACHMENTS ATTACHMENTS_DIR FORUM_LOGIN_URL FORUM_USERNAME FORUM_PASSWORD FORUM_SESSION_COOKIE_NAME FORUM_SESSION_COOKIE; do v=$(printenv "$k"); if [ -n "$v" ]; then echo "$k=set len=${#v}"; else echo "$k=empty"; fi; done'
```

Размер папки вложений и количество файлов:

```bash
docker compose exec -T app sh -lc 'd="${ATTACHMENTS_DIR:-/data/attachments}"; echo "DIR=$d"; du -sh "$d"; echo -n "FILES="; find "$d" -type f | wc -l'
```

20 самых больших файлов во вложениях:

```bash
docker compose exec -T app sh -lc 'd="${ATTACHMENTS_DIR:-/data/attachments}"; find "$d" -type f -printf "%s %p\n" | sort -nr | head -20'
```

## Локальный запуск без Docker (опционально)

1. Поднимите PostgreSQL и настройте `DATABASE_URL`.
2. Установите зависимости:

```bash
pip install -r requirements.txt
```

3. Примените миграции:

```bash
alembic upgrade head
```

4. Запустите приложение:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Ограничения и этика

- Парсится только публичный контент.
- Учитывается `robots.txt`.
- Обход антибот-защиты не реализован.
- Селекторы парсинга зависят от верстки XenForo и могут требовать обновления при изменениях форума.
