"""Apply ChatApp-owned PostgreSQL tables. Run: python -m cli.migrate"""

from pathlib import Path

from core import config
from core.database import connect, get_schema


def main() -> None:
    migration = (
        Path(config.BASE_DIR) / "migrations" / "001_documents_conversations.sql"
    ).read_text(encoding="utf-8")
    schema = get_schema()
    if schema != "proptech":
        quoted = '"' + schema.replace('"', '""') + '"'
        migration = migration.replace("proptech.", f"{quoted}.")
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration)
    print(f"Migration ChatApp đã hoàn tất trong schema {schema}.")


if __name__ == "__main__":
    main()
