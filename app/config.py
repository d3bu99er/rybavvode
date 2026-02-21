from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    secret_key: str = "change-me"

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/fishingmap"

    forum_root_url: str = "https://www.rusfishing.ru/forum/forums/platnyye-prudy.63/"
    forum_source_name: str = "rusfishing"
    max_forum_pages: int = 3
    max_topic_pages: int = 2
    fetch_interval_seconds: int = 1800
    max_concurrency: int = 3
    requests_per_second: float = 1.5
    http_timeout_seconds: int = 20
    forum_login_url: str = ""
    forum_username: str = ""
    forum_password: str = ""
    forum_session_cookie_name: str = "xf_session"
    forum_session_cookie: str = ""
    attachments_dir: str = "data/attachments"
    download_attachments: bool = True

    geocoder_provider: str = "yandex"
    google_geocoding_api_key: str = ""
    yandex_geocoder_api_key: str = ""
    geocode_ttl_days: int = 30
    min_geo_confidence: float = 0.4

    admin_user: str = "admin"
    admin_password: str = "change-this"


@lru_cache
def get_settings() -> Settings:
    return Settings()
