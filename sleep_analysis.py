from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SleepApkPayload(BaseModel):
    telegram_id: int
    date: str | None = None
    source: str | None = None
    total_sleep_minutes: int = Field(default=0)
    deep_sleep_minutes: int = Field(default=0)
    light_sleep_minutes: int = Field(default=0)
    rem_sleep_minutes: int = Field(default=0)
    awake_minutes: int = Field(default=0)
    raw_debug: dict[str, Any] | None = None


def minutes_to_hm(minutes: int) -> str:
    minutes = max(0, minutes)
    return f"{minutes // 60} ч {minutes % 60} мин"


def safe_percent(part: int, total: int) -> int:
    if total <= 0:
        return 0
    return round(part / total * 100)


def normalize_date(value: str | None) -> str:
    if not value:
        return datetime.now().strftime("%d.%m.%Y")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d.%m.%Y")
    except ValueError:
        return value


def resolved_total_sleep(payload: SleepApkPayload) -> int:
    if payload.total_sleep_minutes > 0:
        return payload.total_sleep_minutes
    return payload.deep_sleep_minutes + payload.light_sleep_minutes + payload.rem_sleep_minutes


def sleep_score(payload: SleepApkPayload) -> tuple[int, list[str]]:
    total = resolved_total_sleep(payload)
    deep = max(0, payload.deep_sleep_minutes)
    rem = max(0, payload.rem_sleep_minutes)
    awake = max(0, payload.awake_minutes)

    score = 100
    notes: list[str] = []

    if total < 360:
        score -= 35
        notes.append("сон сильно короче нормы")
    elif total < 420:
        score -= 18
        notes.append("сон короче желательных 7 часов")
    elif total > 570:
        score -= 8
        notes.append("сон длиннее обычного диапазона")

    deep_percent = safe_percent(deep, total)
    if deep_percent < 10:
        score -= 22
        notes.append("низкая доля глубокого сна")
    elif deep_percent < 15:
        score -= 10
        notes.append("глубокий сон ниже оптимального уровня")

    rem_percent = safe_percent(rem, total)
    if rem_percent < 12:
        score -= 14
        notes.append("REM-сна немного")
    elif rem_percent > 30:
        score -= 5
        notes.append("REM-сна необычно много")

    awake_percent = safe_percent(awake, total + awake)
    if awake_percent > 12:
        score -= 14
        notes.append("много пробуждений")
    elif awake_percent > 7:
        score -= 7
        notes.append("есть заметные пробуждения")

    return max(0, min(100, score)), notes


def build_recommendations(payload: SleepApkPayload, notes: list[str]) -> list[str]:
    total = resolved_total_sleep(payload)
    recommendations: list[str] = []

    if total < 420:
        recommendations.append("Лечь на 20-40 минут раньше и не сдвигать время подъёма.")
    if safe_percent(payload.deep_sleep_minutes, total) < 15:
        recommendations.append("За час до сна убрать яркий экран, тяжёлую еду и интенсивные тренировки.")
    if safe_percent(payload.rem_sleep_minutes, total) < 12:
        recommendations.append("Проверить стресс, поздний кофе и нерегулярный режим.")
    if payload.awake_minutes > 40:
        recommendations.append("Посмотреть, что мешало сну: температура, шум, свет или поздняя вода.")

    if not recommendations:
        recommendations.append("Режим выглядит хорошо. Сохрани похожее время сна и подъёма.")

    return recommendations


def build_sleep_report(payload: SleepApkPayload) -> str:
    total = resolved_total_sleep(payload)
    if total <= 0:
        return (
            "🌙 <b>Данные сна получены</b>\n\n"
            "Но в отчёте нет длительности сна и фаз. Проверь, что Mi Fitness отдаёт сон в Health Connect, "
            "а APK получил разрешение на SleepSession и SleepStage."
        )

    deep = max(0, payload.deep_sleep_minutes)
    light = max(0, payload.light_sleep_minutes)
    rem = max(0, payload.rem_sleep_minutes)
    awake = max(0, payload.awake_minutes)

    deep_percent = safe_percent(deep, total)
    light_percent = safe_percent(light, total)
    rem_percent = safe_percent(rem, total)
    awake_percent = safe_percent(awake, total + awake)

    score, notes = sleep_score(payload)
    recommendations = build_recommendations(payload, notes)

    if score >= 85:
        verdict = "✅ Отличное восстановление"
    elif score >= 70:
        verdict = "🟢 Нормальный сон"
    elif score >= 55:
        verdict = "🟡 Сон средний, есть что улучшить"
    else:
        verdict = "🔴 Сон слабый, восстановление могло пострадать"

    notes_text = "\n".join(f"• {note}" for note in notes) if notes else "• критичных замечаний нет"
    recommendations_text = "\n".join(f"• {item}" for item in recommendations)

    return (
        "🌙 <b>Отчёт о сне</b>\n\n"
        f"📅 Дата: <b>{normalize_date(payload.date)}</b>\n"
        f"📱 Источник: <b>{payload.source or 'Health Connect APK'}</b>\n\n"
        f"🛌 Всего сна: <b>{minutes_to_hm(total)}</b>\n"
        f"🟦 Глубокий: <b>{minutes_to_hm(deep)}</b> · {deep_percent}%\n"
        f"⬜ Лёгкий: <b>{minutes_to_hm(light)}</b> · {light_percent}%\n"
        f"🟪 REM: <b>{minutes_to_hm(rem)}</b> · {rem_percent}%\n"
        f"👁 Пробуждения: <b>{minutes_to_hm(awake)}</b> · {awake_percent}%\n\n"
        f"⭐ Оценка: <b>{score}/100</b>\n"
        f"{verdict}\n\n"
        f"🔎 <b>Замечания</b>\n{notes_text}\n\n"
        f"💡 <b>Рекомендации</b>\n{recommendations_text}\n\n"
        "Важно: это не медицинский диагноз, а бытовая аналитика по данным браслета."
    )
