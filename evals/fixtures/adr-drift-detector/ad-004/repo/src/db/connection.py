"""Production database connection. PostgreSQL only."""
import psycopg2

from config.env import get_database_url


def open_connection():
    return psycopg2.connect(get_database_url())
