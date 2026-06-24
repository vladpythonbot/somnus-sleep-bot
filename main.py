import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher

from api import create_app
from bot_handlers import router
from config import BOT_TOKEN, HOST, PORT, validate_config


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)


async def start_bot(bot: Bot) -> None:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    await dispatcher.start_polling(bot)


async def start_api(bot: Bot) -> None:
    app = create_app(bot)
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    validate_config()
    bot = Bot(BOT_TOKEN)
    try:
        await asyncio.gather(start_bot(bot), start_api(bot))
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
