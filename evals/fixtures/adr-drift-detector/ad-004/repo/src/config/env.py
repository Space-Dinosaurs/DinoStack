"""Single auditable point of environment-variable coupling."""
import os


def get_database_url() -> str:
    return os.environ["DATABASE_URL"]


def get_log_level(default: str = "INFO") -> str:
    return os.environ.get("LOG_LEVEL", default)
