from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.security import ENCRYPTED_VALUE_PREFIX, field_encryptor


def should_encrypt(value: str | None) -> bool:
    return bool(value) and not value.startswith(ENCRYPTED_VALUE_PREFIX)


async def alter_operational_columns(connection) -> None:
    await connection.execute(text("ALTER TABLE users MODIFY COLUMN name TEXT NOT NULL"))
    await connection.execute(text("ALTER TABLE users MODIFY COLUMN email TEXT NULL"))
    await connection.execute(text("ALTER TABLE teacher_feedback MODIFY COLUMN content TEXT NOT NULL"))


async def encrypt_users(connection, *, dry_run: bool) -> int:
    result = await connection.execute(text("SELECT id, name, email FROM users"))
    rows = result.mappings().all()
    count = 0

    for row in rows:
        name = row["name"]
        email = row["email"]
        if not should_encrypt(name) and not should_encrypt(email):
            continue
        count += 1
        if dry_run:
            continue
        await connection.execute(
            text(
                """
                UPDATE users
                SET name = :name, email = :email
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "name": field_encryptor.encrypt(name) if should_encrypt(name) else name,
                "email": field_encryptor.encrypt(email) if should_encrypt(email) else email,
            },
        )

    return count


async def encrypt_feedback(connection, *, dry_run: bool) -> int:
    result = await connection.execute(text("SELECT id, content FROM teacher_feedback"))
    rows = result.mappings().all()
    count = 0

    for row in rows:
        content = row["content"]
        if not should_encrypt(content):
            continue
        count += 1
        if dry_run:
            continue
        await connection.execute(
            text("UPDATE teacher_feedback SET content = :content WHERE id = :id"),
            {
                "id": row["id"],
                "content": field_encryptor.encrypt(content),
            },
        )

    return count


async def main() -> None:
    parser = argparse.ArgumentParser(description="Encrypt existing operational PII values in MySQL.")
    parser.add_argument("--dry-run", action="store_true", help="Report rows that would change without updating data.")
    args = parser.parse_args()

    engine = create_async_engine(settings.DB_URL, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            if not args.dry_run:
                await alter_operational_columns(connection)

            user_count = await encrypt_users(connection, dry_run=args.dry_run)
            feedback_count = await encrypt_feedback(connection, dry_run=args.dry_run)

        mode = "would encrypt" if args.dry_run else "encrypted"
        print(f"{mode} {user_count} user row(s) and {feedback_count} teacher feedback row(s).")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
