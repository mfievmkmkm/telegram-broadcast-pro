from aiogram.types import CallbackQuery, Message
from ..db import repo


async def role_of(user_id: int) -> str | None:
    admin = await repo.get_admin(user_id)
    return admin.role if admin else None


async def require(event: Message | CallbackQuery, minimum: str = "viewer") -> bool:
    user = event.from_user
    if not user or not await repo.role_at_least(user.id, minimum):
        if isinstance(event, CallbackQuery):
            await event.answer("⛔ Недостаточно прав", show_alert=True)
        else:
            await event.answer("⛔ Нет доступа к админ-панели")
        return False
    return True
