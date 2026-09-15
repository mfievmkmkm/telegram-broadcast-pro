import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import settings
from .db import init_db
from .handlers.panel import router
from .services.broadcast import BroadcastService
from .services.userbot import user_sender


async def main():
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is empty")
    if not settings.owner_ids:
        raise RuntimeError("OWNER_IDS is empty")

    if settings.database_url.startswith("sqlite"):
        os.makedirs("data", exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    await init_db()
    await user_sender.start()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    service = BroadcastService()
    worker_task = asyncio.create_task(service.worker(), name="campaign-worker")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        worker_task.cancel()
        await user_sender.stop()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
