import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL


# Luôn nạp đúng file .env ở thư mục gốc của project.
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_FILE, override=True)


def _parse_dotnet_connection_string(value: str) -> dict[str, str]:
    """
    Chuyển chuỗi kết nối kiểu .NET:

    Host=...;Port=5432;Database=postgres;
    Username=...;Password=...;SSL Mode=Require

    thành dictionary Python.
    """
    parts: dict[str, str] = {}

    for item in value.split(";"):
        item = item.strip()

        if not item or "=" not in item:
            continue

        key, raw_value = item.split("=", 1)

        normalized_key = key.strip().lower()
        normalized_value = raw_value.strip().strip('"').strip("'")

        parts[normalized_key] = normalized_value

    return parts


def get_database_schema() -> str:
    """
    Lấy schema PostgreSQL.

    Ưu tiên:
    1. Database__Schema
    2. DATABASE_SCHEMA
    3. public
    """
    schema = (
        os.getenv("Database__Schema")
        or os.getenv("DATABASE_SCHEMA")
        or "public"
    )

    schema = schema.strip()

    if not schema:
        return "public"

    return schema


def get_database_url() -> URL | str:
    """
    Lấy URL kết nối database.

    Hỗ trợ:
    - DATABASE_URL dạng PostgreSQL URL.
    - ConnectionStrings__DefaultConnection dạng .NET.
    """
    direct_url = os.getenv("DATABASE_URL")

    if direct_url:
        direct_url = direct_url.strip().strip('"').strip("'")

        # Một số nền tảng cung cấp postgres:// thay vì postgresql://.
        if direct_url.startswith("postgres://"):
            direct_url = direct_url.replace(
                "postgres://",
                "postgresql+psycopg://",
                1,
            )
        elif direct_url.startswith("postgresql://"):
            direct_url = direct_url.replace(
                "postgresql://",
                "postgresql+psycopg://",
                1,
            )

        return direct_url

    connection_string = os.getenv(
        "ConnectionStrings__DefaultConnection"
    )

    if not connection_string:
        raise RuntimeError(
            f"Không tìm thấy cấu hình database trong {ENV_FILE}. "
            "Cần khai báo DATABASE_URL hoặc "
            "ConnectionStrings__DefaultConnection."
        )

    values = _parse_dotnet_connection_string(connection_string)

    host = (
        values.get("host")
        or values.get("server")
        or values.get("data source")
    )

    port_raw = values.get("port", "5432")

    try:
        port = int(port_raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Port PostgreSQL không hợp lệ: {port_raw}"
        ) from exc

    database = (
        values.get("database")
        or values.get("initial catalog")
        or "postgres"
    )

    username = (
        values.get("username")
        or values.get("user id")
        or values.get("userid")
        or values.get("user")
        or values.get("uid")
    )

    password = (
        values.get("password")
        or values.get("pwd")
    )

    missing_fields: list[str] = []

    if not host:
        missing_fields.append("Host")

    if not username:
        missing_fields.append("Username")

    if not password:
        missing_fields.append("Password")

    if missing_fields:
        raise RuntimeError(
            "ConnectionStrings__DefaultConnection thiếu: "
            + ", ".join(missing_fields)
        )

    return URL.create(
        drivername="postgresql+psycopg",
        username=username,
        password=password,
        host=host,
        port=port,
        database=database,
    )


def create_database_engine() -> Engine:
    """
    Tạo SQLAlchemy Engine kết nối PostgreSQL/Supabase.
    """
    schema = get_database_schema()

    return create_engine(
        get_database_url(),
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=10,
        connect_args={
            "sslmode": "require",
            "options": f"-c search_path={schema},public",
            "connect_timeout": 15,
        },
    )