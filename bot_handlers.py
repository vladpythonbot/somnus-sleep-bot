import re


from aiogram import Router
from aiogram.filters import Command
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from sleep_analysis import build_sleep_report, build_statistics_report
from sleep_storage import get_recent_reports, init_db, update_latest_wake_time


router = Router()

TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")




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
        "<code>/fixsleep 07:30</code>\n\n"
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
            "Если браслет сел ночью, просто укажи реальное время подъёма.\n"
            "Бот сам пересчитает последнюю ночь от времени засыпания.\n\n"
            "Пример:\n"
            "<code>/fixsleep 07:30</code>",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    wake_time = parse_clock_time(parts[1])
    if wake_time is None:
        await message.answer(
            "Напиши только время подъёма, например: <code>/fixsleep 07:30</code>.",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    corrected = update_latest_wake_time(message.from_user.id, wake_time)
    if corrected is None:
        await message.answer(
            "Не получилось исправить сон. Нужна сохранённая последняя ночь с временем засыпания.",
            reply_markup=main_keyboard(),
        )
        return

    history = get_recent_reports(message.from_user.id)
    await message.answer(
        "✏️ Время подъёма исправлено.\n"
        "Эта ночь защищена от повторной автоматической перезаписи.\n\n"
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
