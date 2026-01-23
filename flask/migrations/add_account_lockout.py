#!/usr/bin/env python3
"""Add LockedUntil column to Account table for account lockout functionality."""

import os
import pymysql
from dotenv import load_dotenv


def _load_env():
    load_dotenv()
    if not os.getenv("DB_HOST"):
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def get_connection():
    _load_env()
    host = os.getenv("DB_HOST")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    database = os.getenv("DB_NAME")
    port = int(os.getenv("DB_PORT", "3306"))

    if not all([host, user, password, database]):
        raise RuntimeError("Missing DB credentials (DB_HOST, DB_USER, DB_PASSWORD, DB_NAME)")

    return pymysql.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        port=port,
        autocommit=False,
        charset="utf8mb4",
    )


def add_locked_until_column(cursor):
    """Add LockedUntil column to Account table if it doesn't exist."""
    # Check if column already exists
    cursor.execute("""
        SELECT COUNT(*) 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = 'Account'
        AND COLUMN_NAME = 'LockedUntil'
    """)
    exists = cursor.fetchone()[0] > 0
    
    if exists:
        print("LockedUntil column already exists in Account table.")
        return
    
    # Add the column
    cursor.execute("""
        ALTER TABLE Account
        ADD COLUMN LockedUntil DATETIME NULL
        COMMENT 'Account lockout expiration time - locks account for 15 minutes after 5 failed login attempts'
    """)
    print("[OK] Added LockedUntil column to Account table")


def main():
    try:
        conn = get_connection()
    except Exception as exc:  # pragma: no cover
        print(f"[ERROR] Failed to connect to database: {exc}")
        return

    try:
        with conn.cursor() as cursor:
            print("Adding LockedUntil column to Account table...")
            add_locked_until_column(cursor)
            print("[OK] Migration completed successfully")

        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"[ERROR] Migration failed: {exc}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

