from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ChatType


async def check_chat_rights(bot: Bot, chat_id: int) -> tuple[bool, str]:
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        status = member.status
        if status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
            return False, "бот не состоит в чате"

        chat = await bot.get_chat(chat_id)
        if chat.type == ChatType.CHANNEL:
            if status != ChatMemberStatus.ADMINISTRATOR:
                return False, "в канале бот должен быть администратором"
            if getattr(member, "can_post_messages", False) is not True:
                return False, "нет права can_post_messages"
        elif status == ChatMemberStatus.RESTRICTED and not getattr(member, "can_send_messages", False):
            return False, "боту запрещено отправлять сообщения"
        return True, "права на отправку выглядят корректно"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
