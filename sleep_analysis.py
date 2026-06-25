from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SleepApkPayload(BaseModel):
    telegram_id: int
    date: str | None = None
    source: str | None = None
    app_build: str | None = None
    sleep_start: str | None = None
    sleep_end: str | None = None
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


def format_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%H:%M")
    except ValueError:
        return None


def time_to_minutes(value: str | None) -> int | None:
    if not value:
        return None
    formatted = format_time(value)
    if not formatted:
        return None
    hours, minutes = formatted.split(":")
    return int(hours) * 60 + int(minutes)


def resolved_total_sleep(payload: SleepApkPayload) -> int:
    if payload.total_sleep_minutes > 0:
        return payload.total_sleep_minutes
    return payload.deep_sleep_minutes + payload.light_sleep_minutes + payload.rem_sleep_minutes


def bounded_score(value: int) -> int:
    return max(0, min(100, value))


def recovery_index(payload: SleepApkPayload) -> tuple[int, dict[str, int], list[str]]:
    total = resolved_total_sleep(payload)
    deep = max(0, payload.deep_sleep_minutes)
    rem = max(0, payload.rem_sleep_minutes)
    awake = max(0, payload.awake_minutes)

    notes: list[str] = []

    duration_score = bounded_score(round(100 - abs(total - 480) / 180 * 100))
    if 420 <= total <= 540:
        duration_score = max(duration_score, 88)
    elif total < 360:
        notes.append("длительность сна заметно ниже 7 часов")
    elif total < 420:
        notes.append("сон немного короче желательного диапазона")
    elif total > 600:
        notes.append("сон сильно длиннее обычного диапазона")

    # Wellness ranges, not medical thresholds.
    deep_percent = safe_percent(deep, total)
    deep_score = bounded_score(round(100 - abs(deep_percent - 18) / 18 * 100))
    if 13 <= deep_percent <= 25:
        deep_score = max(deep_score, 82)
    elif deep_percent < 10:
        notes.append("глубокого сна мало относительно общей длительности")
    elif deep_percent < 13:
        notes.append("глубокий сон немного ниже желаемого диапазона")

    rem_percent = safe_percent(rem, total)
    rem_score = bounded_score(round(100 - abs(rem_percent - 22) / 18 * 100))
    if 15 <= rem_percent <= 30:
        rem_score = max(rem_score, 82)
    elif rem_percent < 12:
        notes.append("REM-сна немного")
    elif rem_percent > 32:
        notes.append("REM-сна больше обычного диапазона")

    awake_percent = safe_percent(awake, total + awake)
    awake_score = bounded_score(round(100 - awake_percent / 18 * 100))
    if awake_percent <= 8:
        awake_score = max(awake_score, 82)
    elif awake_percent > 12:
        notes.append("много пробуждений")
    elif awake_percent > 8:
        notes.append("есть заметные пробуждения")

    parts = {
        "duration": duration_score,
        "deep": deep_score,
        "rem": rem_score,
        "awake": awake_score,
    }
    index = round(
        duration_score * 0.35
        + deep_score * 0.25
        + rem_score * 0.20
        + awake_score * 0.20
    )
    return bounded_score(index), parts, notes


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


def build_debug_summary(raw_debug: dict[str, Any] | None) -> str:
    if not raw_debug:
        return ""

    fields = [
        ("APK build", "app_build", ""),
        ("окно чтения", "read_window_days", "дн."),
        ("SleepSession записей", "session_record_count", ""),
        ("SleepStage записей", "stage_record_count", ""),
        ("карт обработано", "visited_maps", ""),
        ("записей с длительностью", "duration_records", ""),
        ("распознано фаз", "classified_stage_records", ""),
        ("минут фаз", "stage_total", ""),
        ("минут сессий", "session_total", ""),
    ]
    lines: list[str] = []
    for label, key, suffix in fields:
        value = raw_debug.get(key)
        if value is not None:
            suffix_text = f" {suffix}" if suffix else ""
            lines.append(f"• {label}: <b>{value}</b>{suffix_text}")

    for sample_key, title in [("session_sample", "пример SleepSession"), ("stage_sample", "пример SleepStage")]:
        sample = raw_debug.get(sample_key)
        if isinstance(sample, dict) and not sample.get("empty"):
            keys = sample.get("keys")
            stage_code = sample.get("stage_code")
            duration = sample.get("duration_minutes")
            start_parsed = sample.get("start_parsed")
            end_parsed = sample.get("end_parsed")
            sample_parts: list[str] = []
            if keys:
                sample_parts.append(f"keys: {', '.join(map(str, keys))}")
            if stage_code is not None:
                sample_parts.append(f"stage_code: {stage_code}")
            if duration is not None:
                sample_parts.append(f"duration: {duration} мин")
            if start_parsed:
                sample_parts.append(f"start: {start_parsed}")
            if end_parsed:
                sample_parts.append(f"end: {end_parsed}")
            if sample_parts:
                lines.append(f"• {title}: <code>{' | '.join(sample_parts)}</code>")

    if not lines:
        return ""
    return "\n\n🔎 <b>Диагностика</b>\n" + "\n".join(lines)


def average(values: list[int]) -> int:
    if not values:
        return 0
    return round(sum(values) / len(values))


def average_clock(values: list[int], night_start: bool = False) -> str | None:
    if not values:
        return None
    normalized = [value + 24 * 60 if night_start and value < 12 * 60 else value for value in values]
    return minutes_to_clock(average(normalized))


def build_period_stats(records: list[SleepApkPayload], title: str, target_days: int) -> str:
    period = records[:target_days]
    if not period:
        return f"<b>{title}</b>\nПока нет сохранённых ночей."

    totals = [resolved_total_sleep(item) for item in period]
    deep_values = [max(0, item.deep_sleep_minutes) for item in period]
    rem_values = [max(0, item.rem_sleep_minutes) for item in period]
    awake_values = [max(0, item.awake_minutes) for item in period]
    indexes = [recovery_index(item)[0] for item in period]

    avg_total = average(totals)
    avg_deep_percent = safe_percent(average(deep_values), avg_total)
    avg_rem_percent = safe_percent(average(rem_values), avg_total)
    avg_awake = average(awake_values)
    avg_index = average(indexes)

    starts = [value for value in (time_to_minutes(item.sleep_start) for item in period) if value is not None]
    ends = [value for value in (time_to_minutes(item.sleep_end) for item in period) if value is not None]
    avg_start = average_clock(starts, night_start=True)
    avg_end = average_clock(ends)

    trend = ""
    if len(period) >= 4:
        recent_half = period[: max(2, len(period) // 2)]
        previous_half = period[max(2, len(period) // 2):]
        if previous_half:
            recent_sleep = average([resolved_total_sleep(item) for item in recent_half])
            previous_sleep = average([resolved_total_sleep(item) for item in previous_half])
            diff = recent_sleep - previous_sleep
            if abs(diff) >= 20:
                direction = "больше" if diff > 0 else "меньше"
                trend = f"\nТренд: последние ночи в среднем на {abs(diff)} мин {direction}."

    time_line = ""
    if avg_start and avg_end:
        time_line = f"\nСредний режим: {avg_start} → {avg_end}"

    return (
        f"<b>{title}</b>\n"
        f"Ночей: {len(period)}/{target_days}\n"
        f"Средний сон: {minutes_to_hm(avg_total)}\n"
        f"Глубокий: {avg_deep_percent}% · REM: {avg_rem_percent}%\n"
        f"Пробуждения: {minutes_to_hm(avg_awake)}\n"
        f"Индекс: {avg_index}/100"
        f"{time_line}"
        f"{trend}"
    )


def minutes_to_clock(minutes: int) -> str:
    minutes = minutes % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def build_history_summary(history: list[SleepApkPayload] | None) -> str:
    if not history:
        return ""

    week = build_period_stats(history, "📈 За 7 дней", 7)
    month = build_period_stats(history, "📆 За 30 дней", 30)

    conclusion = ""
    if len(history) >= 7:
        week_records = history[:7]
        avg_index = average([recovery_index(item)[0] for item in week_records])
        avg_total = average([resolved_total_sleep(item) for item in week_records])
        if avg_index >= 80 and 420 <= avg_total <= 540:
            conclusion = "\n\nВывод: режим выглядит устойчиво, главное — сохранить похожее время подъёма."
        elif avg_total < 420:
            conclusion = "\n\nВывод: главный резерв сейчас — добрать длительность сна."
        else:
            conclusion = "\n\nВывод: смотри на стабильность времени сна и количество пробуждений."
    elif history:
        conclusion = "\n\nВывод: статистика уже копится, полноценный анализ появится после 7 ночей."

    return f"\n\n{week}\n\n{month}{conclusion}"


def build_sleep_report(payload: SleepApkPayload, history: list[SleepApkPayload] | None = None) -> str:
    total = resolved_total_sleep(payload)
    if total <= 0:
        debug_text = build_debug_summary(payload.raw_debug)
        return (
            "🌙 <b>Данные сна получены</b>\n\n"
            "Но в отчёте нет длительности сна и фаз. Теперь бот показывает диагностику ниже: "
            "если SleepSession/SleepStage = 0, значит Mi Fitness пока не передал сон в Health Connect или нет разрешений. "
            "Если записи есть, но фаз 0 — нужно подстроить парсер под формат данных телефона."
            f"{debug_text}"
        )

    deep = max(0, payload.deep_sleep_minutes)
    light = max(0, payload.light_sleep_minutes)
    rem = max(0, payload.rem_sleep_minutes)
    awake = max(0, payload.awake_minutes)

    deep_percent = safe_percent(deep, total)
    light_percent = safe_percent(light, total)
    rem_percent = safe_percent(rem, total)
    awake_percent = safe_percent(awake, total + awake)
    sleep_start = format_time(payload.sleep_start)
    sleep_end = format_time(payload.sleep_end)
    sleep_window = ""
    if sleep_start and sleep_end:
        sleep_window = f"🌙 Заснул: <b>{sleep_start}</b>\n☀️ Проснулся: <b>{sleep_end}</b>\n"

    index, index_parts, notes = recovery_index(payload)
    recommendations = build_recommendations(payload, notes)

    if index >= 85:
        verdict = "✅ Сон выглядит восстановительным"
    elif index >= 70:
        verdict = "🟢 Общая картина сна хорошая"
    elif index >= 55:
        verdict = "🟡 Сон средний, есть слабые места"
    else:
        verdict = "🔴 Сон мог восстановить хуже обычного"

    notes_text = "\n".join(f"• {note}" for note in notes) if notes else "• критичных замечаний нет"
    recommendations_text = "\n".join(f"• {item}" for item in recommendations)
    history_text = build_history_summary(history)
    index_text = (
        f"• длительность: {index_parts['duration']}/100\n"
        f"• глубокий сон: {index_parts['deep']}/100\n"
        f"• REM: {index_parts['rem']}/100\n"
        f"• пробуждения: {index_parts['awake']}/100"
    )

    return (
        "🌙 <b>Отчёт о сне</b>\n\n"
        f"📅 Дата: <b>{normalize_date(payload.date)}</b>\n"
        f"{sleep_window}"
        f"🛌 Всего сна: <b>{minutes_to_hm(total)}</b>\n"
        f"🟦 Глубокий: <b>{minutes_to_hm(deep)}</b> · {deep_percent}%\n"
        f"⬜ Лёгкий: <b>{minutes_to_hm(light)}</b> · {light_percent}%\n"
        f"🟪 REM: <b>{minutes_to_hm(rem)}</b> · {rem_percent}%\n"
        f"👁 Пробуждения: <b>{minutes_to_hm(awake)}</b> · {awake_percent}%\n\n"
        f"⭐ Индекс восстановления: <b>{index}/100</b>\n"
        f"{verdict}\n\n"
        f"📊 <b>Из чего сложился индекс</b>\n{index_text}\n\n"
        f"🔎 <b>Замечания</b>\n{notes_text}\n\n"
        f"💡 <b>Рекомендации</b>\n{recommendations_text}"
        f"{history_text}"
    )
