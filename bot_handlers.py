from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message


router = Router()


@router.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer(
        "Привет 👋\n\n"
        "Я принимаю данные сна из Android Health Connect APK и присылаю отчёт прямо в Telegram.\n\n"
        "Твой Telegram ID:\n"
        f"<code>{message.from_user.id}</code>\n\n"
        "Он понадобится в APK.",
        parse_mode="HTML",
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
        "Нажми в APK кнопку <b>Запустить и выдать разрешения</b> и разреши доступ к данным сна.\n\n"
        "5️⃣ <b>Автоматически</b>\n"
        "Раз в сутки APK прочитает SleepSession/SleepStage из Health Connect и отправит отчёт сюда.\n\n"
        "Endpoint сервера:\n"
        "<code>https://YOUR_DOMAIN/webhook/sleep-apk</code>"
    )
    await message.answer(text, parse_mode="HTML")
