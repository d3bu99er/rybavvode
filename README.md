# FishingMap MVP

Production-ready MVP сервиса для парсинга публичных сообщений ветки платных прудов, геокодинга топиков и отображения на карте.

## Что делает
- Парсит публичные топики и посты из ветки:
  - `https://www.rusfishing.ru/forum/forums/platnyye-prudy.63/`
- Сохраняет в PostgreSQL с дедупликацией (`topics` и `posts` по `external_id`).
- Геокодит `place_name` топика через официальный API (Google или Yandex).
- Показывает маркеры постов на `folium` карте (координаты берутся от `topics`).
- Имеет админку с soft-delete/restore постов.
- Фоновое обновление через APScheduler.

## Важно по этике и ToS
- Учитывается `robots.txt` перед загрузкой страниц.
- Нет обхода капчи, блокировок, скрытых endpoint'ов.
- Парсинг только публичного контента.
- Если нужна авторизация, используйте заранее полученную cookie в env и расширьте `httpx` headers безопасно; автоматизация обхода защиты не реализована.
- Геокодинг только через официальные API.

## Стек
- Python 3.11+
- FastAPI
- SQLAlchemy 2.x + Alembic
- httpx + BeautifulSoup4
- APScheduler
- folium
- PostgreSQL
- Docker + docker-compose

## Быстрый старт
1. Скопируйте env:
```bash
cp .env.example .env
```
2. Заполните секреты и ключи API в `.env`:
- `SECRET_KEY`
- `ADMIN_USER`, `ADMIN_PASSWORD`
- `GOOGLE_GEOCODING_API_KEY` или `YANDEX_GEOCODER_API_KEY`

3. Запустите:
```bash
docker compose up --build
```

4. Откройте:
- Карта: `http://localhost:8000/`
- Админка: `http://localhost:8000/admin/login`
- API: `http://localhost:8000/api/posts`

## Alembic
Миграция уже в проекте: `alembic/versions/0001_init.py`

Локально:
```bash
alembic upgrade head
uvicorn app.main:app --reload
```

## API
- `GET /health`
- `GET /api/posts?since=&has_geo=true&include_deleted=false&q=&limit=100&offset=0`
- `GET /api/posts/{id}`
- `GET /api/topics/{id}`

## Админка
- `GET /admin/login`
- `POST /admin/login`
- `GET /admin/posts`
- `POST /admin/posts/{id}/delete`
- `POST /admin/posts/{id}/restore`

## Тесты
```bash
pytest
```

## Переменные окружения
См. `.env.example`.

Ключевые:
- `MAX_FORUM_PAGES`, `MAX_TOPIC_PAGES`, `FETCH_INTERVAL_SECONDS`
- `MAX_CONCURRENCY`, `REQUESTS_PER_SECOND`, `HTTP_TIMEOUT_SECONDS`
- `FORUM_SESSION_COOKIE` (опционально, если публичного доступа недостаточно)
- `GEOCODER_PROVIDER=google|yandex`
- `GEOCODE_TTL_DAYS`, `MIN_GEO_CONFIDENCE`

## Ограничения MVP
- Селекторы под XenForo-подобную структуру и могут требовать подстройки при изменении верстки.
- Для MVP `place_name = title`.
- Админ-аутентификация базовая (session + env credentials).
