import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import settings
from .handlers.public_panel import router
from .multi_db import init_multi_db
from .services.multi_broadcast import multi_broadcast


async def main():
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is empty")
    if not settings.api_id or not settings.api_hash:
        raise RuntimeError("API_ID and API_HASH are required for Telegram account login")

    if settings.database_url.startswith("sqlite"):
        os.makedirs("data", exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    await init_multi_db()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    worker_task = asyncio.create_task(multi_broadcast.worker(), name="multi-broadcast-worker")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        worker_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
