from aiogram import Router
from aiogram.filters import Command
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from sleep_analysis import build_statistics_report
from sleep_storage import get_recent_reports, init_db


router = Router()


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие",
    )


@router.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer(
        "Привет 👋\n\n"
        "Я принимаю данные сна из Android Health Connect APK и присылаю отчёт прямо в Telegram.\n\n"
        "Твой Telegram ID:\n"
        f"<code>{message.from_user.id}</code>\n\n"
        "Он понадобится в APK.",
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
        "Открой APK Somnus Sync, введи URL сервера, свой Telegram ID и webhook secret.\n\n"
        "Твой Telegram ID:\n"
        f"<code>{user_id}</code>\n\n"
        "4️⃣ <b>Разрешения</b>\n"
        "Нажми в APK кнопку <b>Сохранить и включить</b> и разреши доступ к данным сна.\n\n"
        "5️⃣ <b>Автоматически</b>\n"
        "APK смотрит время подъёма, ждёт выбранную задержку и отправляет утренний отчёт один раз за ночь.\n\n"
        "Статистика за 7 и 30 дней доступна по кнопке <b>📊 Статистика</b>.\n\n"
        "Endpoint сервера:\n"
        "<code>https://YOUR_DOMAIN/webhook/sleep-apk</code>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_keyboard())


@router.message(lambda message: message.text in {"📊 Статистика", "Статистика", "/stats"})
async def stats(message: Message) -> None:
    init_db()
    history = get_recent_reports(message.from_user.id)
    await message.answer(
        build_statistics_report(history),
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


@router.message(lambda message: message.text == "ℹ️ Помощь")
async def help_button(message: Message) -> None:
    await help_command(message)
