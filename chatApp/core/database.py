"""PostgreSQL connection helpers for the Prop-Tech knowledge source."""

from contextlib import contextmanager
import re

import psycopg

from core import config


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _from_dotnet_connection_string(value: str) -> str:
    """Convert the Npgsql key/value format used by ASP.NET to a psycopg DSN."""
    parts = {}
    for item in value.split(";"):
        if not item.strip() or "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        parts[key.strip().lower().replace(" ", "")] = raw_value.strip()

    aliases = {
        "host": "host",
        "server": "host",
        "port": "port",
        "database": "dbname",
        "username": "user",
        "userid": "user",
        "user": "user",
        "password": "password",
    }
    dsn_parts = []
    for source, target in aliases.items():
        if source in parts and not any(part.startswith(f"{target}=") for part in dsn_parts):
            escaped = parts[source].replace("\\", "\\\\").replace("'", "\\'")
            dsn_parts.append(f"{target}='{escaped}'")

    ssl_mode = parts.get("sslmode")
    if ssl_mode:
        dsn_parts.append(f"sslmode='{ssl_mode.lower()}'")
    return " ".join(dsn_parts)


def get_postgres_dsn() -> str:
    value = (config.POSTGRES_DSN or "").strip()
    if not value:
        raise RuntimeError(
            "Chưa cấu hình PostgreSQL. Hãy đặt POSTGRES_DSN hoặc DATABASE_URL."
        )
    if "://" not in value and ";" in value:
        value = _from_dotnet_connection_string(value)
    return value


def get_schema() -> str:
    schema = config.POSTGRES_SCHEMA.strip()
    if not _SCHEMA_RE.fullmatch(schema):
        raise RuntimeError(f"POSTGRES_SCHEMA không hợp lệ: {schema!r}")
    return schema


@contextmanager
def connect():
    # prepare_threshold=None: tắt server-side prepared statement vì DSN trỏ qua
    # Supabase transaction-mode pooler (pgbouncer), vốn không giữ prepared
    # statement ổn định giữa các lần mượn connection từ pool.
    with psycopg.connect(
        get_postgres_dsn(), connect_timeout=10, prepare_threshold=None
    ) as connection:
        yield connection


def check_connection() -> dict:
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            database, user = cursor.fetchone()
    return {"database": database, "user": user, "schema": get_schema()}
