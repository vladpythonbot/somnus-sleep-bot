from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from os import getenv
from pathlib import Path

from sleep_analysis import SleepApkPayload, recovery_index, resolved_total_sleep


def default_db_path() -> Path:
    if getenv("DB_PATH"):
        return Path(getenv("DB_PATH", "sleep_bot.db"))
    railway_volume = Path("/data")
    if railway_volume.exists():
        return railway_volume / "sleep_bot.db"
    return Path("sleep_bot.db")


DB_PATH = default_db_path()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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
                is_manual_corrected INTEGER NOT NULL DEFAULT 0,
                UNIQUE(telegram_id, date_key)
            )
            """
        )
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(sleep_reports)").fetchall()
        }
        if "is_manual_corrected" not in existing_columns:
            connection.execute(
                "ALTER TABLE sleep_reports ADD COLUMN is_manual_corrected INTEGER NOT NULL DEFAULT 0"
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
                sleep_start = CASE
                    WHEN sleep_reports.is_manual_corrected = 1 THEN sleep_reports.sleep_start
                    ELSE excluded.sleep_start
                END,
                sleep_end = CASE
                    WHEN sleep_reports.is_manual_corrected = 1 THEN sleep_reports.sleep_end
                    ELSE excluded.sleep_end
                END,
                total_sleep_minutes = CASE
                    WHEN sleep_reports.is_manual_corrected = 1 THEN sleep_reports.total_sleep_minutes
                    ELSE excluded.total_sleep_minutes
                END,
                deep_sleep_minutes = CASE
                    WHEN sleep_reports.is_manual_corrected = 1 THEN sleep_reports.deep_sleep_minutes
                    ELSE excluded.deep_sleep_minutes
                END,
                light_sleep_minutes = CASE
                    WHEN sleep_reports.is_manual_corrected = 1 THEN sleep_reports.light_sleep_minutes
                    ELSE excluded.light_sleep_minutes
                END,
                rem_sleep_minutes = CASE
                    WHEN sleep_reports.is_manual_corrected = 1 THEN sleep_reports.rem_sleep_minutes
                    ELSE excluded.rem_sleep_minutes
                END,
                awake_minutes = CASE
                    WHEN sleep_reports.is_manual_corrected = 1 THEN sleep_reports.awake_minutes
                    ELSE excluded.awake_minutes
                END,
                recovery_index = CASE
                    WHEN sleep_reports.is_manual_corrected = 1 THEN sleep_reports.recovery_index
                    ELSE excluded.recovery_index
                END
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



def update_latest_wake_time(telegram_id: int, wake_time: str) -> SleepApkPayload | None:
    history = get_recent_reports(telegram_id, limit=1)
    if not history:
        return None

    latest = history[0]
    if not latest.sleep_start:
        return None

    try:
        start_dt = datetime.fromisoformat(latest.sleep_start.replace("Z", "+00:00"))
    except ValueError:
        return None

    date_key_value = report_date_key(latest)
    end_dt = datetime.fromisoformat(f"{date_key_value}T{wake_time}:00")
    if start_dt.tzinfo is not None:
        end_dt = end_dt.replace(tzinfo=start_dt.tzinfo)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    awake_minutes = max(0, latest.awake_minutes)
    total_sleep_minutes = round((end_dt - start_dt).total_seconds() / 60) - awake_minutes
    if total_sleep_minutes < 60 or total_sleep_minutes > 16 * 60:
        return None

    corrected = SleepApkPayload(
        telegram_id=latest.telegram_id,
        date=latest.date,
        sleep_start=latest.sleep_start,
        sleep_end=end_dt.isoformat(timespec="seconds"),
        total_sleep_minutes=total_sleep_minutes,
        deep_sleep_minutes=latest.deep_sleep_minutes,
        light_sleep_minutes=max(0, total_sleep_minutes - latest.deep_sleep_minutes - latest.rem_sleep_minutes),
        rem_sleep_minutes=latest.rem_sleep_minutes,
        awake_minutes=awake_minutes,
    )
    index, _, _ = recovery_index(corrected)

    with connect() as connection:
        connection.execute(
            """
            UPDATE sleep_reports
            SET sleep_end = ?,
                total_sleep_minutes = ?,
                light_sleep_minutes = ?,
                recovery_index = ?,
                received_at = ?,
                is_manual_corrected = 1
            WHERE telegram_id = ? AND date_key = ?
            """,
            (
                corrected.sleep_end,
                corrected.total_sleep_minutes,
                corrected.light_sleep_minutes,
                index,
                datetime.now().isoformat(timespec="seconds"),
                telegram_id,
                report_date_key(latest),
            ),
        )

    return corrected
