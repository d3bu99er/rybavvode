import secrets

from app.config import get_settings

SESSION_KEY = "admin_authenticated"


def verify_admin_credentials(username: str, password: str) -> bool:
    settings = get_settings()
    return secrets.compare_digest(username, settings.admin_user) and secrets.compare_digest(password, settings.admin_password)
