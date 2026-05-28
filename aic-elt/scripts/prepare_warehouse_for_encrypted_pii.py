from __future__ import annotations

import os
from contextlib import closing

import psycopg


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def connect_warehouse() -> psycopg.Connection:
    return psycopg.connect(
        host=required_env("WAREHOUSE_DB_HOST"),
        port=int(os.getenv("WAREHOUSE_DB_PORT", "5432")),
        user=required_env("WAREHOUSE_DB_USER"),
        password=required_env("WAREHOUSE_DB_PASSWORD"),
        dbname=required_env("WAREHOUSE_DB_NAME"),
    )


def main() -> None:
    statements = [
        "ALTER TABLE IF EXISTS raw_users ALTER COLUMN name TYPE TEXT",
        "ALTER TABLE IF EXISTS raw_users ALTER COLUMN email TYPE TEXT",
        "ALTER TABLE IF EXISTS stg_submission_metrics ALTER COLUMN student_name TYPE TEXT",
        "ALTER TABLE IF EXISTS mart_student_assignment_metrics ALTER COLUMN student_name TYPE TEXT",
    ]

    with closing(connect_warehouse()) as connection:
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        connection.commit()

    print("Warehouse PII columns are ready for encrypted values.")


if __name__ == "__main__":
    main()
