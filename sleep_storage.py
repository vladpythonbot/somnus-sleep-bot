from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from sleep_analysis import SleepApkPayload, recovery_index, resolved_total_sleep


DB_PATH = Path("sleep_bot.db")


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sleep_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                date_key TEXT NOT NULL,
                received_at TEXT NOT NULL,
                sleep_start TEXT,
                sleep_end TEXT,
                total_sleep_minutes INTEGER NOT NULL,
                deep_sleep_minutes INTEGER NOT NULL,
                light_sleep_minutes INTEGER NOT NULL,
                rem_sleep_minutes INTEGER NOT NULL,
                awake_minutes INTEGER NOT NULL,
                recovery_index INTEGER NOT NULL,
                UNIQUE(telegram_id, date_key)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_sleep_reports_user_date ON sleep_reports(telegram_id, date_key)"
        )


def report_date_key(payload: SleepApkPayload) -> str:
    for value in (payload.sleep_end, payload.date, payload.sleep_start):
        if not value:
            continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.now().strftime("%Y-%m-%d")


def save_sleep_report(payload: SleepApkPayload) -> None:
    index, _, _ = recovery_index(payload)
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO sleep_reports (
                telegram_id, date_key, received_at, sleep_start, sleep_end,
                total_sleep_minutes, deep_sleep_minutes, light_sleep_minutes,
                rem_sleep_minutes, awake_minutes, recovery_index
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id, date_key) DO UPDATE SET
                received_at = excluded.received_at,
                sleep_start = excluded.sleep_start,
                sleep_end = excluded.sleep_end,
                total_sleep_minutes = excluded.total_sleep_minutes,
                deep_sleep_minutes = excluded.deep_sleep_minutes,
                light_sleep_minutes = excluded.light_sleep_minutes,
                rem_sleep_minutes = excluded.rem_sleep_minutes,
                awake_minutes = excluded.awake_minutes,
                recovery_index = excluded.recovery_index
            """,
            (
                payload.telegram_id,
                report_date_key(payload),
                datetime.now().isoformat(timespec="seconds"),
                payload.sleep_start,
                payload.sleep_end,
                resolved_total_sleep(payload),
                max(0, payload.deep_sleep_minutes),
                max(0, payload.light_sleep_minutes),
                max(0, payload.rem_sleep_minutes),
                max(0, payload.awake_minutes),
                index,
            ),
        )


def get_recent_reports(telegram_id: int, limit: int = 30) -> list[SleepApkPayload]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM sleep_reports
            WHERE telegram_id = ?
            ORDER BY date_key DESC
            LIMIT ?
            """,
            (telegram_id, limit),
        ).fetchall()

    reports: list[SleepApkPayload] = []
    for row in rows:
        reports.append(
            SleepApkPayload(
                telegram_id=row["telegram_id"],
                date=row["date_key"],
                sleep_start=row["sleep_start"],
                sleep_end=row["sleep_end"],
                total_sleep_minutes=row["total_sleep_minutes"],
                deep_sleep_minutes=row["deep_sleep_minutes"],
                light_sleep_minutes=row["light_sleep_minutes"],
                rem_sleep_minutes=row["rem_sleep_minutes"],
                awake_minutes=row["awake_minutes"],
            )
        )
    return reports
