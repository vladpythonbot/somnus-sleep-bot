import re
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from sleep_analysis import build_sleep_report, build_statistics_report
from sleep_storage import get_recent_reports, init_db, update_total_sleep


router = Router()

DATE_PATTERN = re.compile(r"^\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?$|^\d{4}-\d{1,2}-\d{1,2}$")
TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")


def parse_sleep_minutes(value: str) -> int | None:
    value = value.strip().lower().replace(",", ".")
    if not value:
        return None

    if ":" in value:
        hours_text, minutes_text = value.split(":", 1)
        if not hours_text.isdigit() or not minutes_text.isdigit():
            return None
        return int(hours_text) * 60 + int(minutes_text)

    if value.endswith("ч"):
        value = value[:-1].strip()

    number = float(value) if value.replace(".", "", 1).isdigit() else None
    if number is None:
        return None

    if number <= 24:
        return round(number * 60)
    return round(number)


def parse_date_key(value: str) -> str | None:
    value = value.strip().rstrip(",")
    if not DATE_PATTERN.match(value):
        return None

    current_year = datetime.now().year
    try:
        if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", value):
            return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")

        separator = "." if "." in value else "/" if "/" in value else "-"
        parts = value.split(separator)
        day = int(parts[0])
        month = int(parts[1])
        year = current_year
        if len(parts) == 3:
            year = int(parts[2])
            if year < 100:
                year += 2000
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_clock_time(value: str) -> str | None:
    value = value.strip().lower().replace("wake=", "").replace("подъем=", "").replace("подъём=", "")
    if not TIME_PATTERN.match(value):
        return None
    hours_text, minutes_text = value.split(":", 1)
    hours = int(hours_text)
    minutes = int(minutes_text)
    if hours > 23 or minutes > 59:
        return None
    return f"{hours:02d}:{minutes:02d}"


def parse_fixsleep_args(raw_args: str) -> tuple[int | None, str | None, str | None]:
    duration_minutes: int | None = None
    target_date_key: str | None = None
    wake_time: str | None = None

    for token in raw_args.split():
        normalized = token.strip().rstrip(",")
        if not normalized:
            continue

        if target_date_key is None:
            target_date_key = parse_date_key(normalized)
            if target_date_key:
                continue

        if normalized.lower().startswith(("wake=", "подъем=", "подъём=")):
            wake_time = parse_clock_time(normalized)
            continue

        if duration_minutes is None:
            duration_minutes = parse_sleep_minutes(normalized)
            if duration_minutes is not None:
                continue

        if wake_time is None:
            wake_time = parse_clock_time(normalized)

    return duration_minutes, target_date_key, wake_time


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌙 Последний сон"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="⚙️ Настройка"), KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Сон, статистика или настройка",
    )


@router.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer(
        "🌙 <b>Somnus</b>\n\n"
        "Я присылаю анализ сна после подъёма и веду статистику за 7/30 дней.\n\n"
        "Твой Telegram ID:\n"
        f"<code>{message.from_user.id}</code>\n\n"
        "Он понадобится в APK. Дальше нажми <b>⚙️ Настройка</b>.",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    user_id = message.from_user.id
    text = (
        "🌙 <b>Как работает Somnus</b>\n\n"
        "1️⃣ <b>Mi Fitness</b>\n"
        "Браслет Xiaomi синхронизирует сон в официальное приложение Mi Fitness.\n\n"
        "2️⃣ <b>Health Connect</b>\n"
        "В Android Health Connect разреши Mi Fitness записывать данные сна.\n\n"
        "3️⃣ <b>Наш APK</b>\n"
        "Открой APK Somnus Sync, введи свой Telegram ID и webhook secret.\n\n"
        "Твой Telegram ID:\n"
        f"<code>{user_id}</code>\n\n"
        "4️⃣ <b>Разрешения</b>\n"
        "Нажми в APK кнопку <b>Сохранить и включить</b> и разреши доступ к данным сна.\n\n"
        "5️⃣ <b>Отчёт после подъёма</b>\n"
        "APK смотрит время подъёма, ждёт выбранную задержку и отправляет утренний отчёт один раз за ночь.\n\n"
        "Если браслет сел и сон записался не полностью, исправь последнюю ночь:\n"
        "<code>/fixsleep 8:00</code>\n\n"
        "Статистика за 7 и 30 дней доступна по кнопке <b>📊 Статистика</b>."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_keyboard())


@router.message(Command("last"))
@router.message(lambda message: message.text in {"🌙 Последний сон", "Последний сон", "/last"})
async def last_sleep(message: Message) -> None:
    init_db()
    history = get_recent_reports(message.from_user.id)
    if not history:
        await message.answer(
            "🌙 <b>Последний сон</b>\n\n"
            "Пока нет сохранённых отчётов. Нажми в APK <b>Отправить тест сейчас</b> "
            "или дождись первой автоматической отправки.",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    await message.answer(
        build_sleep_report(history[0], history),
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


@router.message(Command("stats"))
@router.message(lambda message: message.text in {"📊 Статистика", "Статистика", "/stats"})
async def stats(message: Message) -> None:
    init_db()
    history = get_recent_reports(message.from_user.id)
    await message.answer(
        build_statistics_report(history),
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


@router.message(Command("fixsleep"))
async def fix_sleep(message: Message) -> None:
    init_db()
    command_text = message.text or ""
    parts = command_text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "✏️ <b>Поправка сна</b>\n\n"
            "Если браслет сел или снялся, можно исправить длительность сна.\n\n"
            "Примеры:\n"
            "<code>/fixsleep 8:00</code> — последняя ночь\n"
            "<code>/fixsleep 26.06 8:00</code> — конкретная дата\n"
            "<code>/fixsleep 26.06 8:00 07:30</code> — дата, длительность и время подъёма",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    minutes, target_date_key, wake_time = parse_fixsleep_args(parts[1])
    if minutes is None or minutes < 60 or minutes > 16 * 60:
        await message.answer(
            "Не понял длительность. Напиши так: <code>/fixsleep 8:00</code> или <code>/fixsleep 26.06 8:00 07:30</code>.",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    corrected = update_total_sleep(
        message.from_user.id,
        minutes,
        target_date_key=target_date_key,
        wake_time=wake_time,
    )
    if corrected is None:
        date_hint = f" за {target_date_key}" if target_date_key else ""
        await message.answer(
            f"Нет сохранённой ночи{date_hint}. Сначала должен прийти хотя бы один отчёт из APK.",
            reply_markup=main_keyboard(),
        )
        return

    history = get_recent_reports(message.from_user.id)
    details = []
    if target_date_key:
        details.append(f"дата: <b>{target_date_key}</b>")
    if wake_time:
        details.append(f"подъём: <b>{wake_time}</b>")
    details_text = "\n".join(f"• {item}" for item in details)
    if details_text:
        details_text += "\n\n"

    await message.answer(
        "✏️ Сон исправлен вручную.\n"
        "Автоматическая отправка APK больше не перезатрёт эту ночь.\n\n"
        f"{details_text}"
        + build_sleep_report(corrected, history),
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


@router.message(lambda message: message.text == "ℹ️ Помощь")
async def help_button(message: Message) -> None:
    await help_command(message)


@router.message(Command("setup"))
@router.message(lambda message: message.text in {"⚙️ Настройка", "Настройка"})
async def setup_info(message: Message) -> None:
    await message.answer(
        "⚙️ <b>Настройка отправки</b>\n\n"
        "Отчёт приходит не по фиксированному будильнику, а после реального подъёма:\n"
        "1. APK находит время подъёма в Health Connect.\n"
        "2. Ждёт выбранную задержку: 15, 30, 45, 60 или 90 минут.\n"
        "3. Отправляет отчёт один раз за эту ночь.\n\n"
        "<b>Что влияет на время прихода</b>\n"
        "• когда Mi Fitness передал сон в Health Connect;\n"
        "• выбранная задержка после подъёма;\n"
        "• интернет на телефоне;\n"
        "• энергосбережение Android;\n"
        "• разрешена ли фоновая работа APK;\n"
        "• WorkManager: Android может выполнить задачу чуть позже, чтобы экономить батарею.\n\n"
        "<b>Чтобы приходило стабильнее</b>\n"
        "Открой настройки Android для Somnus Sync и разреши фоновую работу без жёсткой экономии батареи.",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )
